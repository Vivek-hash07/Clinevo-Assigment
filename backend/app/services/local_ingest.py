"""Create queue messages from local fixtures or uploaded PDFs (no Gmail required)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.constants import SOURCE_FIXTURE, SOURCE_UPLOAD, STATUS_PROCESSING, STATUS_READY, STATUS_REVIEWED
from app.jobqueue import store as queue_store
from app.jobqueue.handlers import KIND_EMAIL_INGESTED, KIND_PDF_ATTACHED
from app.jobqueue.types import JobEvent
from app.models import Attachment, Message, PdfPage, User
from app.services.audit import write_audit
from app.services.mail_types import checksum_bytes
from app.services import storage
from app.services.synthetic import SyntheticEmail, catalog_by_key, synthetic_catalog

_PDF_MAGIC = b"%PDF"
_MAX_UPLOAD_FILES = 12


class LocalIngestError(Exception):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _pdf_payload(message: Message) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for attachment in message.attachments:
        if attachment.skipped or not attachment.storage_key:
            continue
        mime = (attachment.mime or "").lower()
        if not (mime.startswith("application/pdf") or attachment.filename.lower().endswith(".pdf")):
            continue
        if attachment.processed:
            continue
        rows.append(
            {
                "id": attachment.id,
                "checksum": attachment.checksum,
                "filename": attachment.filename,
            }
        )
    return rows


def enqueue_message_pipeline(user_id: str, message: Message) -> list[str]:
    """Kick off the pipeline for a message that did not come from a mailbox.

    Idempotency keys only collide with jobs that are still queued or running, so
    re-submitting a finished document re-runs it while a double click does not.
    """
    pdfs = _pdf_payload(message)
    if pdfs:
        events = [
            JobEvent(
                kind=KIND_PDF_ATTACHED,
                payload={
                    "user_id": user_id,
                    "message_id": message.id,
                    "attachment_id": item["id"],
                    "checksum": item["checksum"],
                    "filename": item.get("filename"),
                },
                idempotency_key=f"pdf-{message.id}-{item['checksum']}",
                user_id=user_id,
                message_id=message.id,
            )
            for item in pdfs
        ]
    else:
        events = [
            JobEvent(
                kind=KIND_EMAIL_INGESTED,
                payload={"message_id": message.id, "user_id": user_id},
                idempotency_key=f"email-ingested-{message.id}",
                user_id=user_id,
                message_id=message.id,
            )
        ]
    return queue_store.enqueue(events)


def _store_pdf(
    db: Session,
    message: Message,
    filename: str,
    data: bytes,
    existing_checksums: set[str],
) -> Attachment | None:
    settings = get_settings()
    if not data:
        return None
    if len(data) > settings.attachment_max_bytes:
        raise LocalIngestError("PDF is larger than the configured attachment limit.", 413)
    checksum = checksum_bytes(data)
    if checksum in existing_checksums:
        return None
    key = storage.put_bytes(checksum, data, suffix=".pdf")
    attachment = Attachment(
        message_id=message.id,
        filename=(filename or "upload.pdf")[:512],
        mime="application/pdf",
        checksum=checksum,
        processed=False,
        skipped=False,
        storage_key=key,
        size_bytes=len(data),
    )
    db.add(attachment)
    message.attachments.append(attachment)
    existing_checksums.add(checksum)
    return attachment


def _store_skipped_non_pdf(
    db: Session,
    message: Message,
    filename: str,
    mime: str,
    data: bytes,
    existing_checksums: set[str],
) -> None:
    checksum = checksum_bytes(data) if data else checksum_bytes(filename.encode("utf-8"))
    if checksum in existing_checksums:
        return
    db.add(
        Attachment(
            message_id=message.id,
            filename=filename[:512],
            mime=mime or "application/octet-stream",
            checksum=checksum,
            processed=False,
            skipped=True,
            skip_reason="non_pdf",
            size_bytes=len(data) if data else None,
        )
    )
    existing_checksums.add(checksum)


def ingest_email_record(
    db: Session,
    user: User,
    item: SyntheticEmail,
    *,
    source: str = SOURCE_FIXTURE,
) -> tuple[Message, bool]:
    settings = get_settings()
    existing = db.scalar(
        select(Message).where(Message.user_id == user.id, Message.fixture_key == item.key)
    )
    if existing is not None and existing.status in {STATUS_READY, STATUS_REVIEWED}:
        return existing, False
    if existing is not None:
        return existing, True

    body = _clip(item.text_body, settings.message_body_max_chars)
    message = Message(
        user_id=user.id,
        source=source,
        fixture_key=item.key,
        sender=f"{item.sender_name} <synthetic@example.test>",
        subject=item.subject[:1024],
        sent_at=datetime.now(UTC),
        snippet=_clip(body, 2048),
        body=body,
        status=STATUS_PROCESSING,
    )
    db.add(message)
    db.flush()
    checksums: set[str] = set()
    for filename, mime, blob in item.attachments:
        if (mime or "").lower().startswith("application/pdf") or filename.lower().endswith(".pdf"):
            _store_pdf(db, message, filename, blob, checksums)
        else:
            _store_skipped_non_pdf(db, message, filename, mime, blob, checksums)
            write_audit(
                db,
                "gmail.attachment_skipped",
                user.id,
                {"filename": filename, "mime": mime, "reason": "non_pdf", "source": source},
                message_id=message.id,
            )
    write_audit(
        db,
        "email.ingested",
        user.id,
        {"source": source, "fixture_key": item.key, "pdfs": len(_pdf_payload(message))},
        message_id=message.id,
    )
    return message, True


def load_fixture_messages(
    db: Session,
    user: User,
    keys: list[str] | None = None,
    *,
    source: str = SOURCE_FIXTURE,
) -> list[Message]:
    catalog = catalog_by_key()
    selected = keys or [item.key for item in synthetic_catalog()]
    unknown = [key for key in selected if key not in catalog]
    if unknown:
        raise LocalIngestError(f"Unknown fixture keys: {', '.join(unknown)}")
    rows: list[Message] = []
    for key in selected:
        message, _ = ingest_email_record(db, user, catalog[key], source=source)
        rows.append(message)
    db.flush()
    return rows


def _assert_pdf_bytes(filename: str, data: bytes) -> None:
    name = (filename or "upload.pdf").strip() or "upload.pdf"
    if not name.lower().endswith(".pdf"):
        raise LocalIngestError(f"{name} is not a PDF. Only PDFs are processed.")
    if not data:
        raise LocalIngestError(f"{name} is empty.")
    head = data[:1024]
    if _PDF_MAGIC not in head:
        raise LocalIngestError(
            f"{name} does not look like a PDF (missing %PDF header). "
            "Export or re-save the file as PDF and try again."
        )


def ingest_uploads(
    db: Session,
    user: User,
    files: list[tuple[str, bytes]],
    *,
    subject: str | None = None,
    note: str | None = None,
) -> Message:
    if not files:
        raise LocalIngestError("Upload at least one PDF.")
    if len(files) > _MAX_UPLOAD_FILES:
        raise LocalIngestError(f"Upload at most {_MAX_UPLOAD_FILES} PDFs at a time.")
    settings = get_settings()
    names = [name for name, _ in files]
    for filename, data in files:
        _assert_pdf_bytes(filename, data)
    body = (note or "").strip() or (
        "Uploaded outside Gmail for literature screening. Synthetic / test documents only. "
        f"Files: {', '.join(names)}."
    )
    message = Message(
        user_id=user.id,
        source=SOURCE_UPLOAD,
        sender=f"{user.name or 'Reviewer'} <{user.email}>",
        subject=(subject or f"Uploaded PDF — {names[0]}")[:1024],
        sent_at=datetime.now(UTC),
        snippet=_clip(body, 2048),
        body=_clip(body, settings.message_body_max_chars),
        status=STATUS_PROCESSING,
    )
    db.add(message)
    db.flush()
    checksums: set[str] = set()
    stored = 0
    for filename, data in files:
        if _store_pdf(db, message, filename, data, checksums):
            stored += 1
    if stored == 0:
        raise LocalIngestError("Those PDFs were empty or already attached to this upload.")
    write_audit(
        db,
        "upload.received",
        user.id,
        {"filenames": names, "pdfs": stored},
        message_id=message.id,
    )
    return message


def copy_attachment_with_pages(db: Session, source: Attachment, dest_message: Message) -> Attachment:
    clone = Attachment(
        message_id=dest_message.id,
        filename=source.filename,
        mime=source.mime,
        checksum=source.checksum,
        processed=source.processed,
        skipped=source.skipped,
        skip_reason=source.skip_reason,
        storage_key=source.storage_key,
        size_bytes=source.size_bytes,
        page_count=source.page_count,
        document_flavor=source.document_flavor,
        extract_error=source.extract_error,
        processed_at=source.processed_at,
        duration_ms=source.duration_ms,
    )
    db.add(clone)
    dest_message.attachments.append(clone)
    db.flush()
    for page in source.pages:
        db.add(
            PdfPage(
                attachment_id=clone.id,
                page_number=page.page_number,
                text=page.text,
                original_text=page.original_text,
                translated_text=page.translated_text,
                language=page.language,
                language_confidence=page.language_confidence,
                ocr_confidence=page.ocr_confidence,
                llm_score=page.llm_score,
                flavor=page.flavor,
                extract_method=page.extract_method,
                column_count=page.column_count,
                char_count=page.char_count,
                word_count=page.word_count,
                tables=page.tables,
                image_notes=page.image_notes,
                needs_human_review=page.needs_human_review,
                review_reasons=page.review_reasons,
                source_ref=f"pdf:{clone.id}:page:{page.page_number}",
                prompt_version=page.prompt_version,
                model=page.model,
            )
        )
    return clone
