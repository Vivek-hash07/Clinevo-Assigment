from __future__ import annotations

import inngest

from app.inngest_client import inngest_client
from app.services.ai_pipeline import (
    classify_message,
    extract_facts,
    mark_ai_failed,
    understand_message,
)
from app.services.gmail_client import GmailAuthError, GmailApiError
from app.services.ingest import (
    IngestSkip,
    discover_mailbox_messages,
    ingest_gmail_message,
    list_all_syncable_user_ids,
    save_mailbox_cursor,
)
from app.services.pdf_pipeline import (
    finalize_pdf_attachment,
    inspect_pdf_attachment,
    mark_pdf_failed,
    process_pdf_page,
)


@inngest_client.create_function(
    fn_id="gmail-sync",
    name="gmail/sync",
    trigger=inngest.TriggerCron(cron="*/2 * * * *", jitter="20s"),
    retries=2,
)
async def gmail_sync(ctx: inngest.Context) -> dict:
    user_ids = await ctx.step.run("list-mailboxes", list_all_syncable_user_ids)
    if not user_ids:
        return {"mailboxes": 0}
    await ctx.step.send_event(
        "fan-out-mailboxes",
        [
            inngest.Event(
                name="gmail/sync.mailbox",
                id=f"gmail-sync-mailbox-{user_id}-{ctx.run_id}",
                data={"user_id": user_id},
            )
            for user_id in user_ids
        ],
    )
    return {"mailboxes": len(user_ids)}


@inngest_client.create_function(
    fn_id="gmail-sync-mailbox",
    name="gmail/sync mailbox",
    trigger=inngest.TriggerEvent(event="gmail/sync.mailbox"),
    retries=4,
    concurrency=[inngest.Concurrency(limit=1, key="event.data.user_id")],
    singleton=inngest.Singleton(key="event.data.user_id", mode="skip"),
)
async def gmail_sync_mailbox(ctx: inngest.Context) -> dict:
    user_id = str(ctx.event.data["user_id"])
    discovered = await ctx.step.run("list-new-messages", discover_mailbox_messages, user_id)
    if discovered.get("error"):
        raise inngest.NonRetriableError(str(discovered["error"]))
    message_ids = list(discovered.get("message_ids") or [])
    history_id = discovered.get("history_id")
    if message_ids:
        await ctx.step.send_event(
            "enqueue-ingest",
            [
                inngest.Event(
                    name="email/received",
                    id=f"email-received-{user_id}-{gmail_id}",
                    data={"user_id": user_id, "gmail_message_id": gmail_id},
                )
                for gmail_id in message_ids
            ],
        )
    await ctx.step.run("save-history-cursor", save_mailbox_cursor, user_id, history_id)
    return {"queued": len(message_ids), "history_id": history_id}


@inngest_client.create_function(
    fn_id="email-ingest",
    name="email/ingest",
    trigger=inngest.TriggerEvent(event="email/received"),
    retries=4,
    concurrency=[inngest.Concurrency(limit=2, key="event.data.user_id")],
    idempotency="event.data.user_id + '-' + event.data.gmail_message_id",
)
async def email_ingest(ctx: inngest.Context) -> dict:
    user_id = str(ctx.event.data["user_id"])
    gmail_message_id = str(ctx.event.data["gmail_message_id"])
    try:
        result = await ctx.step.run(
            "fetch-and-persist",
            ingest_gmail_message,
            user_id,
            gmail_message_id,
            ctx.run_id,
        )
    except IngestSkip as exc:
        raise inngest.NonRetriableError(str(exc)) from exc
    except GmailAuthError as exc:
        raise inngest.NonRetriableError(str(exc)) from exc
    except GmailApiError as exc:
        if exc.status_code == 404:
            raise inngest.NonRetriableError(exc.detail) from exc
        raise
    attachments = list(result.get("pdf_attachments") or [])
    message_id = result.get("message_id")
    if attachments and message_id:
        await ctx.step.send_event(
            "fan-out-pdfs",
            [
                inngest.Event(
                    name="pdf/attached",
                    id=f"pdf-{message_id}-{item['checksum']}",
                    data={
                        "user_id": user_id,
                        "message_id": message_id,
                        "attachment_id": item["id"],
                        "checksum": item["checksum"],
                        "filename": item.get("filename"),
                    },
                )
                for item in attachments
            ],
        )
    elif message_id and not result.get("skipped") and result.get("status") != "reviewed":
        await ctx.step.send_event(
            "email-ingested",
            inngest.Event(
                name="email/ingested",
                id=f"email-ingested-{message_id}",
                data={"message_id": message_id, "user_id": user_id},
            ),
        )
    return result


@inngest_client.create_function(
    fn_id="pdf-process",
    name="pdf/process",
    trigger=inngest.TriggerEvent(event="pdf/attached"),
    retries=3,
    concurrency=[
        inngest.Concurrency(limit=2, key="event.data.user_id"),
        inngest.Concurrency(limit=4),
    ],
    idempotency="event.data.message_id + '-' + event.data.checksum",
)
async def pdf_process(ctx: inngest.Context) -> dict:
    attachment_id = str(ctx.event.data["attachment_id"])
    try:
        meta = await ctx.step.run("inspect-pdf", inspect_pdf_attachment, attachment_id, ctx.run_id)
        if meta.get("retryable"):
            raise RuntimeError(str(meta.get("reason") or "pdf_inspect_retryable"))
        if meta.get("skip"):
            return meta
        page_count = int(meta["page_count"])
        for page_number in range(1, page_count + 1):
            await ctx.step.run(
                f"extract-page-{page_number}",
                process_pdf_page,
                attachment_id,
                page_number,
                ctx.run_id,
            )
        result = await ctx.step.run("finalize-pdf", finalize_pdf_attachment, attachment_id, ctx.run_id)
        if result.get("emit_extracted") and result.get("message_id"):
            await ctx.step.send_event(
                "pdf-extracted",
                inngest.Event(
                    name="pdf/extracted",
                    id=f"pdf-extracted-{result['message_id']}",
                    data={
                        "message_id": result["message_id"],
                        "user_id": result.get("user_id"),
                    },
                ),
            )
        return result
    except inngest.NonRetriableError:
        await ctx.step.run("mark-failed", mark_pdf_failed, attachment_id, ctx.run_id, "non_retriable")
        raise


@inngest_client.create_function(
    fn_id="ai-understand",
    name="ai/understand",
    trigger=[
        inngest.TriggerEvent(event="pdf/extracted"),
        inngest.TriggerEvent(event="email/ingested"),
    ],
    retries=3,
    concurrency=[
        inngest.Concurrency(limit=2, key="event.data.user_id"),
        inngest.Concurrency(limit=4),
    ],
    idempotency="event.data.message_id + '-understand'",
)
async def ai_understand(ctx: inngest.Context) -> dict:
    message_id = str(ctx.event.data["message_id"])
    try:
        result = await ctx.step.run("understand-message", understand_message, message_id, ctx.run_id)
        if result.get("reason") == "pdfs_open":
            return result
        if result.get("ok") and result.get("message_id") and result.get("reason") != "reviewed":
            await ctx.step.send_event(
                "message-ready",
                inngest.Event(
                    name="message/ready",
                    id=f"message-ready-{result['message_id']}",
                    data={
                        "message_id": result["message_id"],
                        "user_id": result.get("user_id"),
                    },
                ),
            )
        if not result.get("ok") and not result.get("skip"):
            raise inngest.NonRetriableError(str(result.get("reason") or "understand_failed"))
        return result
    except inngest.NonRetriableError:
        await ctx.step.run("mark-failed", mark_ai_failed, message_id, ctx.run_id, "understand_failed")
        raise


@inngest_client.create_function(
    fn_id="ai-classify",
    name="ai/classify",
    trigger=inngest.TriggerEvent(event="message/ready"),
    retries=3,
    concurrency=[
        inngest.Concurrency(limit=2, key="event.data.user_id"),
        inngest.Concurrency(limit=4),
    ],
    idempotency="event.data.message_id + '-classify'",
)
async def ai_classify(ctx: inngest.Context) -> dict:
    message_id = str(ctx.event.data["message_id"])
    try:
        result = await ctx.step.run("classify-message", classify_message, message_id, ctx.run_id)
        if result.get("ok") and result.get("message_id") and result.get("reason") != "reviewed":
            await ctx.step.send_event(
                "message-classified",
                inngest.Event(
                    name="message/classified",
                    id=f"message-classified-{result['message_id']}",
                    data={
                        "message_id": result["message_id"],
                        "user_id": result.get("user_id"),
                        "categories": result.get("categories") or [],
                    },
                ),
            )
        if not result.get("ok") and not result.get("skip"):
            raise inngest.NonRetriableError(str(result.get("reason") or "classify_failed"))
        return result
    except inngest.NonRetriableError:
        await ctx.step.run("mark-failed", mark_ai_failed, message_id, ctx.run_id, "classify_failed")
        raise


@inngest_client.create_function(
    fn_id="ai-extract",
    name="ai/extract",
    trigger=inngest.TriggerEvent(event="message/classified"),
    retries=3,
    concurrency=[
        inngest.Concurrency(limit=2, key="event.data.user_id"),
        inngest.Concurrency(limit=4),
    ],
    idempotency="event.data.message_id + '-extract'",
)
async def ai_extract(ctx: inngest.Context) -> dict:
    message_id = str(ctx.event.data["message_id"])
    try:
        result = await ctx.step.run("extract-facts", extract_facts, message_id, ctx.run_id)
        if result.get("ok") and result.get("screen_literature") and result.get("message_id"):
            await ctx.step.send_event(
                "literature-screen",
                inngest.Event(
                    name="literature/screen",
                    id=f"literature-screen-{result['message_id']}",
                    data={
                        "message_id": result["message_id"],
                        "user_id": result.get("user_id"),
                    },
                ),
            )
        if not result.get("ok") and not result.get("skip"):
            raise inngest.NonRetriableError(str(result.get("reason") or "extract_failed"))
        return result
    except inngest.NonRetriableError:
        await ctx.step.run("mark-failed", mark_ai_failed, message_id, ctx.run_id, "extract_failed")
        raise


@inngest_client.create_function(
    fn_id="ai-literature-screen",
    name="ai/literature-screen",
    trigger=inngest.TriggerEvent(event="literature/screen"),
    retries=3,
    concurrency=[
        inngest.Concurrency(limit=2, key="event.data.user_id"),
        inngest.Concurrency(limit=4),
    ],
)
async def ai_literature_screen(ctx: inngest.Context) -> dict:
    from app.services.literature import screen_literature

    message_id = str(ctx.event.data["message_id"])
    result = await ctx.step.run("screen-literature", screen_literature, message_id, ctx.run_id)
    if not result.get("ok") and not result.get("skip"):
        raise inngest.NonRetriableError(str(result.get("reason") or "literature_screen_failed"))
    return result


INNGEST_FUNCTIONS = [
    gmail_sync,
    gmail_sync_mailbox,
    email_ingest,
    pdf_process,
    ai_understand,
    ai_classify,
    ai_extract,
    ai_literature_screen,
]
