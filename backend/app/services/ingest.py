from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.constants import STATUS_PENDING, STATUS_PROCESSING, STATUS_READY, STATUS_REVIEWED
from app.models import Attachment, GmailCredential, Message, PipelineRun, User
from app.services.audit import write_audit
from app.services.gmail_client import (
    GmailApiError,
    GmailAuthError,
    GmailClient,
    GmailHistoryExpired,
)
from app.services.gmail_parse import ParsedMessage, checksum_bytes, checksum_meta, parse_gmail_message
from app.services import storage


class IngestSkip(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def list_syncable_user_ids(only_user_id: str | None = None) -> list[str]:
    from app.database import session_scope

    with session_scope() as db:
        stmt = select(GmailCredential.user_id).where(
            GmailCredential.sync_enabled.is_(True),
            GmailCredential.refresh_token_encrypted.is_not(None),
        )
        if only_user_id:
            stmt = stmt.where(GmailCredential.user_id == only_user_id)
        return list(db.scalars(stmt).all())


def list_all_syncable_user_ids() -> list[str]:
    return list_syncable_user_ids()


def discover_mailbox_messages(user_id: str) -> dict:
    from app.database import session_scope

    with session_scope() as db:
        cred = db.scalar(
            select(GmailCredential)
            .where(GmailCredential.user_id == user_id)
            .with_for_update()
        )
        if cred is None or not cred.refresh_token_encrypted or not cred.sync_enabled:
            raise IngestSkip("mailbox_not_connected")
        client = GmailClient(db, cred)
        try:
            if cred.history_id:
                try:
                    message_ids, history_id = client.list_history_ids(cred.history_id)
                except GmailHistoryExpired:
                    message_ids, history_id = client.list_inbox_ids()
                    write_audit(
                        db,
                        "gmail.history_expired",
                        user_id,
                        {"previous_history_id": cred.history_id},
                    )
            else:
                message_ids, history_id = client.list_inbox_ids()
        except GmailAuthError as exc:
            return {"message_ids": [], "history_id": cred.history_id, "error": str(exc)}
        except GmailApiError as exc:
            cred.last_error = exc.detail[:1000]
            write_audit(db, "gmail.sync_error", user_id, {"detail": exc.detail, "status": exc.status_code})
            raise
        cred.last_error = None
        write_audit(
            db,
            "gmail.sync_discovered",
            user_id,
            {
                "count": len(message_ids),
                "history_id": history_id,
                "mode": "history" if cred.history_id else "list",
            },
        )
        return {
            "message_ids": message_ids,
            "history_id": history_id,
            "gmail_email": cred.gmail_email,
        }


def save_mailbox_cursor(user_id: str, history_id: str | None) -> dict:
    from app.database import session_scope

    with session_scope() as db:
        cred = db.scalar(select(GmailCredential).where(GmailCredential.user_id == user_id))
        if cred is None:
            return {"saved": False}
        if history_id:
            cred.history_id = history_id
        cred.last_synced_at = datetime.now(UTC)
        cred.last_error = None
        return {"saved": True, "history_id": history_id}


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _download_attachment(client: GmailClient, gmail_message_id: str, parsed) -> bytes:
    if parsed.inline_data:
        return parsed.inline_data
    if parsed.attachment_id:
        return client.get_attachment_bytes(gmail_message_id, parsed.attachment_id)
    return b""


def ingest_gmail_message(user_id: str, gmail_message_id: str, inngest_run_id: str | None = None) -> dict:
    from app.database import session_scope

    settings = get_settings()
    started = datetime.now(UTC)
    with session_scope() as db:
        run = PipelineRun(
            inngest_run_id=inngest_run_id,
            function_name="email/ingest",
            started_at=started,
            status="running",
        )
        db.add(run)
        db.flush()

        existing = db.scalar(
            select(Message).where(
                Message.user_id == user_id,
                Message.gmail_message_id == gmail_message_id,
            )
        )
        if existing is not None and existing.status in {
            STATUS_READY,
            STATUS_REVIEWED,
            STATUS_PENDING,
            STATUS_PROCESSING,
        }:
            if existing.body or existing.attachments:
                payload = _pdf_attachment_payload(existing)
                if payload and existing.status != STATUS_REVIEWED:
                    existing.status = STATUS_PROCESSING
                run.status = "skipped"
                run.finished_at = datetime.now(UTC)
                run.duration_ms = int((run.finished_at - started).total_seconds() * 1000)
                run.message_id = existing.id
                return {
                    "ok": True,
                    "duplicate": True,
                    "message_id": existing.id,
                    "status": existing.status,
                    "pdf_attachments": payload,
                }

        user = db.get(User, user_id)
        cred = db.scalar(select(GmailCredential).where(GmailCredential.user_id == user_id))
        if user is None or cred is None:
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            raise IngestSkip("mailbox_not_connected")

        client = GmailClient(db, cred, settings)
        raw = client.get_message(gmail_message_id)
        parsed = parse_gmail_message(raw)
        if not parsed.is_inbox:
            run.status = "skipped"
            run.finished_at = datetime.now(UTC)
            run.duration_ms = int((run.finished_at - started).total_seconds() * 1000)
            write_audit(
                db,
                "gmail.message_skipped",
                user_id,
                {"gmail_message_id": gmail_message_id, "reason": "not_inbox", "labels": parsed.label_ids},
            )
            return {"ok": True, "skipped": True, "reason": "not_inbox"}

        message = existing or Message(
            user_id=user_id,
            gmail_message_id=gmail_message_id,
            status=STATUS_PROCESSING,
        )
        if existing is None:
            db.add(message)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                winner = db.scalar(
                    select(Message).where(
                        Message.user_id == user_id,
                        Message.gmail_message_id == gmail_message_id,
                    )
                )
                if winner is not None:
                    return {
                        "ok": True,
                        "duplicate": True,
                        "message_id": winner.id,
                        "status": winner.status,
                        "pdf_attachments": _pdf_attachment_payload(winner),
                    }
                raise

        _apply_parsed_message(db, message, parsed, settings)
        stored, skipped = _persist_attachments(db, client, message, parsed, settings)
        payload = _pdf_attachment_payload(message)
        message.status = STATUS_PROCESSING if payload else STATUS_PENDING
        finished = datetime.now(UTC)
        run.message_id = message.id
        run.finished_at = finished
        run.duration_ms = int((finished - started).total_seconds() * 1000)
        run.status = "succeeded"
        write_audit(
            db,
            "email.ingested",
            user_id,
            {
                "gmail_message_id": gmail_message_id,
                "pdfs": stored,
                "skipped_attachments": skipped,
                "duration_ms": run.duration_ms,
            },
            message_id=message.id,
        )
        return {
            "ok": True,
            "duplicate": False,
            "message_id": message.id,
            "status": message.status,
            "pdfs": stored,
            "skipped_attachments": skipped,
            "pdf_attachments": payload,
        }


def _apply_parsed_message(db: Session, message: Message, parsed: ParsedMessage, settings: Settings) -> None:
    message.gmail_thread_id = parsed.thread_id
    message.sender = parsed.sender[:512]
    message.subject = parsed.subject[:1024]
    message.sent_at = parsed.sent_at
    message.snippet = parsed.snippet[:2048]
    message.body = _clip(parsed.body_text, settings.message_body_max_chars)
    if parsed.body_html:
        message.body_html = _clip(parsed.body_html, settings.message_body_max_chars)
    message.status = STATUS_PROCESSING
    db.flush()


def _persist_attachments(
    db: Session,
    client: GmailClient,
    message: Message,
    parsed: ParsedMessage,
    settings: Settings,
) -> tuple[int, int]:
    stored = 0
    skipped = 0
    existing_checksums = {row.checksum for row in message.attachments}
    for part in parsed.attachments:
        if part.is_pdf:
            data = _download_attachment(client, parsed.gmail_id, part)
            size = len(data)
            if size == 0:
                reason = "empty_pdf"
                checksum = checksum_meta(part.attachment_id or "", part.filename, part.mime, "empty")
                _add_skipped(db, message, part, checksum, reason, existing_checksums)
                skipped += 1
                write_audit(
                    db,
                    "gmail.attachment_skipped",
                    message.user_id,
                    {"filename": part.filename, "mime": part.mime, "reason": reason},
                    message_id=message.id,
                )
                continue
            if size > settings.attachment_max_bytes:
                reason = "too_large"
                checksum = checksum_bytes(data[: 1024 * 64] + size.to_bytes(8, "big"))
                _add_skipped(db, message, part, checksum, reason, existing_checksums, size)
                skipped += 1
                write_audit(
                    db,
                    "gmail.attachment_skipped",
                    message.user_id,
                    {"filename": part.filename, "mime": part.mime, "reason": reason, "size_bytes": size},
                    message_id=message.id,
                )
                continue
            checksum = checksum_bytes(data)
            if checksum in existing_checksums:
                continue
            key = storage.put_bytes(checksum, data, suffix=".pdf")
            attachment = Attachment(
                message_id=message.id,
                filename=part.filename[:512],
                mime=part.mime or "application/pdf",
                checksum=checksum,
                processed=False,
                skipped=False,
                storage_key=key,
                gmail_attachment_id=part.attachment_id,
                size_bytes=size,
            )
            db.add(attachment)
            message.attachments.append(attachment)
            existing_checksums.add(checksum)
            stored += 1
            continue

        reason = "non_pdf"
        checksum = checksum_meta(part.attachment_id or "", part.filename, part.mime, str(part.size_bytes or 0))
        _add_skipped(db, message, part, checksum, reason, existing_checksums, part.size_bytes)
        skipped += 1
        write_audit(
            db,
            "gmail.attachment_skipped",
            message.user_id,
            {
                "filename": part.filename,
                "mime": part.mime,
                "reason": reason,
                "size_bytes": part.size_bytes,
            },
            message_id=message.id,
        )
    db.flush()
    return stored, skipped


def _add_skipped(
    db: Session,
    message: Message,
    part,
    checksum: str,
    reason: str,
    existing_checksums: set[str],
    size_bytes: int | None = None,
) -> None:
    if checksum in existing_checksums:
        return
    db.add(
        Attachment(
            message_id=message.id,
            filename=part.filename[:512],
            mime=part.mime or "application/octet-stream",
            checksum=checksum,
            processed=False,
            skipped=True,
            skip_reason=reason,
            gmail_attachment_id=part.attachment_id,
            size_bytes=size_bytes if size_bytes is not None else part.size_bytes,
        )
    )
    existing_checksums.add(checksum)


def _pdf_attachment_payload(message: Message) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for attachment in message.attachments:
        if attachment.skipped or attachment.processed or not attachment.storage_key:
            continue
        mime = (attachment.mime or "").lower()
        if not (mime.startswith("application/pdf") or attachment.filename.lower().endswith(".pdf")):
            continue
        if not attachment.id:
            continue
        rows.append(
            {
                "id": attachment.id,
                "checksum": attachment.checksum,
                "filename": attachment.filename,
            }
        )
    return rows
