"""The document pipeline, expressed as queue handlers.

Each handler does one step and emits the next. Kinds are named after the event that
triggers them, so a row in `queue_jobs` reads as the stage the document reached:

    mail/sync ─► mail/sync.mailbox ─► email/received ─┬─► pdf/attached ─► pdf/extracted ─┐
                                                      └─► email/ingested ────────────────┤
                                                                                         ▼
                          literature/screen ◄── message/classified ◄── message/ready ◄── ai/understand
"""

from __future__ import annotations

import logging

from app.jobqueue.registry import register
from app.jobqueue.types import JobContext, NonRetriableError
from app.services.ai_pipeline import classify_message, extract_facts, mark_ai_failed, understand_message
from app.services.ingest import IngestSkip, discover_mailbox_messages, ingest_mail_message, save_mailbox_cursor
from app.services.mail_errors import MailAuthError, MailProviderError
from app.services.mailboxes import list_syncable_mailboxes
from app.services.pdf_pipeline import (
    finalize_pdf_attachment,
    inspect_pdf_attachment,
    mark_pdf_failed,
    process_pdf_page,
)

logger = logging.getLogger(__name__)

KIND_MAIL_SYNC = "mail/sync"
KIND_MAIL_SYNC_MAILBOX = "mail/sync.mailbox"
KIND_EMAIL_RECEIVED = "email/received"
KIND_PDF_ATTACHED = "pdf/attached"
KIND_PDF_EXTRACTED = "pdf/extracted"
KIND_EMAIL_INGESTED = "email/ingested"
KIND_MESSAGE_READY = "message/ready"
KIND_MESSAGE_CLASSIFIED = "message/classified"
KIND_LITERATURE_SCREEN = "literature/screen"

PIPELINE_STAGES = (
    KIND_MAIL_SYNC,
    KIND_MAIL_SYNC_MAILBOX,
    KIND_EMAIL_RECEIVED,
    KIND_PDF_ATTACHED,
    KIND_PDF_EXTRACTED,
    KIND_EMAIL_INGESTED,
    KIND_MESSAGE_READY,
    KIND_MESSAGE_CLASSIFIED,
    KIND_LITERATURE_SCREEN,
)


@register(KIND_MAIL_SYNC, max_attempts=2, label="Poll every connected mailbox")
def handle_mail_sync(ctx: JobContext) -> dict:
    """Fan out to one job per connected mailbox (Gmail OAuth or IMAP)."""
    only_user = ctx.get("user_id")
    mailboxes = list_syncable_mailboxes(only_user_id=only_user)
    for box in mailboxes:
        ctx.emit(
            KIND_MAIL_SYNC_MAILBOX,
            {"user_id": box.user_id, "provider": box.provider},
            # One live sync per mailbox: a second poll while one is running is dropped.
            idempotency_key=f"mail-sync-{box.provider}-{box.user_id}",
            user_id=box.user_id,
        )
    return {"mailboxes": len(mailboxes), "providers": [box.provider for box in mailboxes]}


@register(KIND_MAIL_SYNC_MAILBOX, max_attempts=4, label="List new messages in one mailbox")
def handle_mail_sync_mailbox(ctx: JobContext) -> dict:
    user_id = ctx.require("user_id")
    provider = ctx.require("provider")
    try:
        discovered = discover_mailbox_messages(user_id, provider)
    except IngestSkip as exc:
        raise NonRetriableError(str(exc)) from exc
    except MailAuthError as exc:
        raise NonRetriableError(str(exc)) from exc

    if discovered.get("error"):
        raise NonRetriableError(str(discovered["error"]))

    message_ids = list(discovered.get("message_ids") or [])
    for provider_message_id in message_ids:
        ctx.emit(
            KIND_EMAIL_RECEIVED,
            {
                "user_id": user_id,
                "provider": provider,
                "provider_message_id": provider_message_id,
            },
            idempotency_key=f"email-received-{provider}-{user_id}-{provider_message_id}",
            user_id=user_id,
        )
    save_mailbox_cursor(user_id, provider, discovered.get("cursor"))
    return {"queued": len(message_ids), "cursor": discovered.get("cursor"), "provider": provider}


@register(KIND_EMAIL_RECEIVED, max_attempts=4, label="Fetch one email and its attachments")
def handle_email_received(ctx: JobContext) -> dict:
    user_id = ctx.require("user_id")
    provider = ctx.require("provider")
    provider_message_id = ctx.require("provider_message_id")
    try:
        result = ingest_mail_message(user_id, provider, provider_message_id, ctx.job_id)
    except IngestSkip as exc:
        raise NonRetriableError(str(exc)) from exc
    except MailAuthError as exc:
        raise NonRetriableError(str(exc)) from exc
    except MailProviderError as exc:
        if exc.status_code == 404:
            raise NonRetriableError(exc.detail) from exc
        raise

    message_id = result.get("message_id")
    attachments = list(result.get("pdf_attachments") or [])
    if message_id:
        _emit_after_ingest(ctx, user_id, str(message_id), attachments, result)
    return result


def _emit_after_ingest(
    ctx: JobContext,
    user_id: str,
    message_id: str,
    attachments: list[dict],
    result: dict,
) -> None:
    if attachments:
        for item in attachments:
            ctx.emit(
                KIND_PDF_ATTACHED,
                {
                    "user_id": user_id,
                    "message_id": message_id,
                    "attachment_id": item["id"],
                    "checksum": item["checksum"],
                    "filename": item.get("filename"),
                },
                idempotency_key=f"pdf-{message_id}-{item['checksum']}",
                user_id=user_id,
                message_id=message_id,
            )
        return
    if result.get("skipped") or result.get("status") == "reviewed":
        return
    ctx.emit(
        KIND_EMAIL_INGESTED,
        {"message_id": message_id, "user_id": user_id},
        idempotency_key=f"email-ingested-{message_id}",
        user_id=user_id,
        message_id=message_id,
    )


@register(KIND_PDF_ATTACHED, max_attempts=3, label="Read one PDF (flavor, OCR, tables, pages)")
def handle_pdf_attached(ctx: JobContext) -> dict:
    attachment_id = ctx.require("attachment_id")
    message_id = ctx.get("message_id")
    try:
        meta = inspect_pdf_attachment(attachment_id, ctx.job_id)
        if meta.get("retryable"):
            # e.g. the stored file is not visible yet; a plain raise gets backoff.
            raise RuntimeError(str(meta.get("reason") or "pdf_inspect_retryable"))
        if meta.get("skip"):
            return meta

        page_count = int(meta["page_count"])
        for page_number in range(1, page_count + 1):
            # Pages upsert by (attachment, page), so a retry re-runs them harmlessly.
            process_pdf_page(attachment_id, page_number, ctx.job_id)

        result = finalize_pdf_attachment(attachment_id, ctx.job_id)
        if result.get("emit_extracted") and result.get("message_id"):
            ctx.emit(
                KIND_PDF_EXTRACTED,
                {"message_id": result["message_id"], "user_id": result.get("user_id")},
                idempotency_key=f"pdf-extracted-{result['message_id']}",
                user_id=result.get("user_id"),
                message_id=str(result["message_id"]),
            )
        return result
    except NonRetriableError:
        mark_pdf_failed(attachment_id, ctx.job_id, "non_retriable")
        raise
    except Exception as exc:
        if ctx.is_last_attempt:
            mark_pdf_failed(attachment_id, ctx.job_id, f"{type(exc).__name__}: {exc}"[:500])
            logger.warning("pdf/attached gave up on %s (message %s)", attachment_id, message_id)
        raise


@register(KIND_PDF_EXTRACTED, max_attempts=3, label="Summarize the message (AI)")
def handle_pdf_extracted(ctx: JobContext) -> dict:
    return _understand(ctx)


@register(KIND_EMAIL_INGESTED, max_attempts=3, label="Summarize the message (AI)")
def handle_email_ingested(ctx: JobContext) -> dict:
    return _understand(ctx)


def _understand(ctx: JobContext) -> dict:
    message_id = ctx.require("message_id")
    try:
        result = understand_message(message_id, ctx.job_id)
        if result.get("reason") == "pdfs_open":
            # Another attachment on this message is still being read; that PDF's own
            # job emits pdf/extracted when it finishes, so stop here without failing.
            return result
        if result.get("ok") and result.get("message_id") and result.get("reason") != "reviewed":
            ctx.emit(
                KIND_MESSAGE_READY,
                {"message_id": result["message_id"], "user_id": result.get("user_id")},
                idempotency_key=f"message-ready-{result['message_id']}",
                user_id=result.get("user_id"),
                message_id=str(result["message_id"]),
            )
        if not result.get("ok") and not result.get("skip"):
            raise NonRetriableError(str(result.get("reason") or "understand_failed"))
        return result
    except NonRetriableError:
        mark_ai_failed(message_id, ctx.job_id, "understand_failed")
        raise
    except Exception:
        if ctx.is_last_attempt:
            mark_ai_failed(message_id, ctx.job_id, "understand_failed")
        raise


@register(KIND_MESSAGE_READY, max_attempts=3, label="Classify into the 4 categories (AI)")
def handle_message_ready(ctx: JobContext) -> dict:
    message_id = ctx.require("message_id")
    try:
        result = classify_message(message_id, ctx.job_id)
        if result.get("ok") and result.get("message_id") and result.get("reason") != "reviewed":
            ctx.emit(
                KIND_MESSAGE_CLASSIFIED,
                {
                    "message_id": result["message_id"],
                    "user_id": result.get("user_id"),
                    "categories": result.get("categories") or [],
                },
                idempotency_key=f"message-classified-{result['message_id']}",
                user_id=result.get("user_id"),
                message_id=str(result["message_id"]),
            )
        if not result.get("ok") and not result.get("skip"):
            raise NonRetriableError(str(result.get("reason") or "classify_failed"))
        return result
    except NonRetriableError:
        mark_ai_failed(message_id, ctx.job_id, "classify_failed")
        raise
    except Exception:
        if ctx.is_last_attempt:
            mark_ai_failed(message_id, ctx.job_id, "classify_failed")
        raise


@register(KIND_MESSAGE_CLASSIFIED, max_attempts=3, label="Extract ICSR / PQC / MI facts (AI)")
def handle_message_classified(ctx: JobContext) -> dict:
    message_id = ctx.require("message_id")
    try:
        result = extract_facts(message_id, ctx.job_id)
        if result.get("ok") and result.get("screen_literature") and result.get("message_id"):
            ctx.emit(
                KIND_LITERATURE_SCREEN,
                {"message_id": result["message_id"], "user_id": result.get("user_id")},
                idempotency_key=f"literature-screen-{result['message_id']}",
                user_id=result.get("user_id"),
                message_id=str(result["message_id"]),
            )
        if not result.get("ok") and not result.get("skip"):
            raise NonRetriableError(str(result.get("reason") or "extract_failed"))
        return result
    except NonRetriableError:
        mark_ai_failed(message_id, ctx.job_id, "extract_failed")
        raise
    except Exception:
        if ctx.is_last_attempt:
            mark_ai_failed(message_id, ctx.job_id, "extract_failed")
        raise


@register(KIND_LITERATURE_SCREEN, max_attempts=3, label="Screen article for identifiable cases (AI)")
def handle_literature_screen(ctx: JobContext) -> dict:
    from app.services.literature import screen_literature

    message_id = ctx.require("message_id")
    result = screen_literature(message_id, ctx.job_id)
    if not result.get("ok") and not result.get("skip"):
        raise NonRetriableError(str(result.get("reason") or "literature_screen_failed"))
    return result
