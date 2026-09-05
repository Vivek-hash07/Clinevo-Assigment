from __future__ import annotations

import inngest

from app.inngest_client import inngest_client
from app.services.gmail_client import GmailAuthError, GmailApiError
from app.services.ingest import (
    IngestSkip,
    discover_mailbox_messages,
    ingest_gmail_message,
    list_all_syncable_user_ids,
    save_mailbox_cursor,
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
        return await ctx.step.run(
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


INNGEST_FUNCTIONS = [gmail_sync, gmail_sync_mailbox, email_ingest]
