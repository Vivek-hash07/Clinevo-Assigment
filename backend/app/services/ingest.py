"""Pull messages out of a connected mailbox and persist them with their PDFs.

Provider-agnostic: everything here works against the `MailProvider` interface, so the
same code path serves Google OAuth and IMAP.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.constants import STATUS_PENDING, STATUS_PROCESSING, STATUS_READY, STATUS_REVIEWED
from app.models import Attachment, GmailCredential, ImapAccount, Message, PipelineRun, User
from app.services import storage
from app.services.audit import write_audit
from app.services.mail_errors import MailAuthError, MailProviderError
from app.services.mail_providers import (
    PROVIDER_GMAIL,
    PROVIDER_IMAP,
    MailProvider,
    open_provider,
)
from app.services.mail_types import ParsedMessage, checksum_bytes, checksum_meta

logger = logging.getLogger(__name__)


class IngestSkip(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# --------------------------------------------------------------------------- discovery


def discover_mailbox_messages(user_id: str, provider: str) -> dict:
    """List message ids that arrived since the stored cursor."""
    from app.database import session_scope
    from app.services.mailboxes import read_cursor

    settings = get_settings()
    with session_scope() as db:
        cursor = read_cursor(db, user_id, provider)
        try:
            client = open_provider(db, user_id, provider)
        except MailAuthError as exc:
            raise IngestSkip(str(exc)) from exc

        try:
            message_ids, new_cursor = client.list_new_message_ids(
                cursor, settings.mail_sync_max_messages
            )
        except MailAuthError as exc:
            _record_error(db, user_id, provider, str(exc), disable=True)
            return {"message_ids": [], "cursor": cursor, "error": str(exc)}
        except MailProviderError as exc:
            _record_error(db, user_id, provider, exc.detail, disable=False)
            write_audit(
                db,
                "mail.sync_error",
                user_id,
                {"provider": provider, "detail": exc.detail, "status": exc.status_code},
            )
            raise
        finally:
            client.close()

        _record_error(db, user_id, provider, None, disable=False)
        write_audit(
            db,
            "mail.sync_discovered",
            user_id,
            {
                "provider": provider,
                "count": len(message_ids),
                "cursor": new_cursor,
                "mode": "incremental" if cursor else "initial",
            },
        )
        return {"message_ids": message_ids, "cursor": new_cursor, "provider": provider}


def save_mailbox_cursor(user_id: str, provider: str, cursor: str | None) -> dict:
    from app.database import session_scope

    with session_scope() as db:
        if provider == PROVIDER_GMAIL:
            cred = db.scalar(select(GmailCredential).where(GmailCredential.user_id == user_id))
            if cred is None:
                return {"saved": False}
            if cursor:
                cred.history_id = cursor
            cred.last_synced_at = datetime.now(UTC)
            cred.last_error = None
            return {"saved": True, "cursor": cursor}

        account = db.scalar(select(ImapAccount).where(ImapAccount.user_id == user_id))
        if account is None:
            return {"saved": False}
        if cursor:
            validity, _, uid = str(cursor).rpartition(":")
            account.uid_validity = validity or account.uid_validity
            if uid.isdigit():
                account.last_uid = int(uid)
        account.last_synced_at = datetime.now(UTC)
        account.last_error = None
        return {"saved": True, "cursor": cursor}


def _record_error(db: Session, user_id: str, provider: str, error: str | None, *, disable: bool) -> None:
    if provider == PROVIDER_GMAIL:
        row = db.scalar(select(GmailCredential).where(GmailCredential.user_id == user_id))
    else:
        row = db.scalar(select(ImapAccount).where(ImapAccount.user_id == user_id))
    if row is None:
        return
    row.last_error = error[:1000] if error else None
    if disable:
        row.sync_enabled = False
        write_audit(db, "mail.auth_revoked", user_id, {"provider": provider, "detail": error})


# ----------------------------------------------------------------------------- ingest


def ingest_mail_message(
    user_id: str,
    provider: str,
    provider_message_id: str,
    run_id: str | None = None,
) -> dict:
    """Fetch one message, store it, and store every PDF attachment."""
    from app.database import session_scope

    settings = get_settings()
    started = datetime.now(UTC)
    with session_scope() as db:
        run = PipelineRun(
            run_id=run_id,
            function_name="email/ingest",
            started_at=started,
            status="running",
        )
        db.add(run)
        db.flush()

        existing = db.scalar(
            select(Message).where(
                Message.user_id == user_id,
                Message.provider_message_id == provider_message_id,
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
                _finish_run(run, started, "skipped", message_id=existing.id)
                return {
                    "ok": True,
                    "duplicate": True,
                    "message_id": existing.id,
                    "status": existing.status,
                    "pdf_attachments": payload,
                }

        user = db.get(User, user_id)
        if user is None:
            _finish_run(run, started, "failed")
            raise IngestSkip("user_missing")

        try:
            client = open_provider(db, user_id, provider)
        except MailAuthError as exc:
            _finish_run(run, started, "failed")
            raise IngestSkip(str(exc)) from exc

        try:
            parsed = client.fetch_message(provider_message_id)
            if not parsed.in_inbox:
                _finish_run(run, started, "skipped")
                write_audit(
                    db,
                    "mail.message_skipped",
                    user_id,
                    {
                        "provider": provider,
                        "provider_message_id": provider_message_id,
                        "reason": "not_inbox",
                        "labels": parsed.label_ids,
                    },
                )
                return {"ok": True, "skipped": True, "reason": "not_inbox"}

            message = existing or Message(
                user_id=user_id,
                provider_message_id=provider_message_id,
                mail_provider=provider,
                status=STATUS_PROCESSING,
            )
            if existing is None:
                db.add(message)
                try:
                    db.flush()
                except IntegrityError:
                    # Another worker ingested the same message first.
                    db.rollback()
                    winner = db.scalar(
                        select(Message).where(
                            Message.user_id == user_id,
                            Message.provider_message_id == provider_message_id,
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

            message.mail_provider = provider
            _apply_parsed_message(db, message, parsed, settings)
            stored, skipped = _persist_attachments(db, client, message, parsed, settings)
        finally:
            client.close()

        payload = _pdf_attachment_payload(message)
        message.status = STATUS_PROCESSING
        duration_ms = _finish_run(run, started, "succeeded", message_id=message.id)
        write_audit(
            db,
            "email.ingested",
            user_id,
            {
                "provider": provider,
                "provider_message_id": provider_message_id,
                "pdfs": stored,
                "skipped_attachments": skipped,
                "duration_ms": duration_ms,
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


def _finish_run(
    run: PipelineRun,
    started: datetime,
    status: str,
    *,
    message_id: str | None = None,
) -> int:
    finished = datetime.now(UTC)
    run.status = status
    run.finished_at = finished
    run.duration_ms = int((finished - started).total_seconds() * 1000)
    if message_id:
        run.message_id = message_id
    return run.duration_ms


def _apply_parsed_message(
    db: Session, message: Message, parsed: ParsedMessage, settings: Settings
) -> None:
    message.provider_thread_id = parsed.thread_id
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
    client: MailProvider,
    message: Message,
    parsed: ParsedMessage,
    settings: Settings,
) -> tuple[int, int]:
    """Store PDFs; record everything else as skipped so the log still shows it arrived."""
    stored = 0
    skipped = 0
    existing_checksums = {row.checksum for row in message.attachments}
    for part in parsed.attachments:
        if not part.is_pdf:
            reason = "non_pdf"
            checksum = checksum_meta(
                part.attachment_id or "", part.filename, part.mime, str(part.size_bytes or 0)
            )
            _add_skipped(db, message, part, checksum, reason, existing_checksums, part.size_bytes)
            skipped += 1
            write_audit(
                db,
                "mail.attachment_skipped",
                message.user_id,
                {
                    "filename": part.filename,
                    "mime": part.mime,
                    "reason": reason,
                    "size_bytes": part.size_bytes,
                },
                message_id=message.id,
            )
            continue

        data = client.fetch_attachment(parsed.provider_message_id, part)
        size = len(data)
        if size == 0:
            reason = "empty_pdf"
            checksum = checksum_meta(
                part.attachment_id or "", part.filename, part.mime, "empty"
            )
            _add_skipped(db, message, part, checksum, reason, existing_checksums)
            skipped += 1
            write_audit(
                db,
                "mail.attachment_skipped",
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
                "mail.attachment_skipped",
                message.user_id,
                {
                    "filename": part.filename,
                    "mime": part.mime,
                    "reason": reason,
                    "size_bytes": size,
                },
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
            provider_attachment_id=part.attachment_id,
            size_bytes=size,
        )
        db.add(attachment)
        message.attachments.append(attachment)
        existing_checksums.add(checksum)
        stored += 1

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
            provider_attachment_id=part.attachment_id,
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


__all__ = [
    "PROVIDER_GMAIL",
    "PROVIDER_IMAP",
    "IngestSkip",
    "discover_mailbox_messages",
    "ingest_mail_message",
    "save_mailbox_cursor",
]
