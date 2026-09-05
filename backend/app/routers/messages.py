from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.constants import QUEUE_STATUSES
from app.deps import CurrentUser, DbSession
from app.models import Attachment, Message, PdfPage
from app.schemas import (
    ClassificationOut,
    ExtractedFieldOut,
    PdfPageOut,
    PdfPagesOut,
    QueueAttachmentOut,
    QueueCounts,
    QueueDetailOut,
    QueueItemOut,
    QueueListOut,
)

router = APIRouter(prefix="/api/messages", tags=["messages"])


def _counts_for(db: DbSession, user_id: str) -> QueueCounts:
    rows = db.execute(
        select(Message.status, func.count()).where(Message.user_id == user_id).group_by(Message.status)
    ).all()
    counts = QueueCounts()
    by_status = {status_name: n for status_name, n in rows}
    counts.pending = int(by_status.get("pending") or 0)
    counts.processing = int(by_status.get("processing") or 0)
    counts.ready = int(by_status.get("ready") or 0)
    counts.reviewed = int(by_status.get("reviewed") or 0)
    counts.total = counts.pending + counts.processing + counts.ready + counts.reviewed
    return counts


def _item_out(row: Message) -> QueueItemOut:
    pdfs = 0
    skipped = 0
    for attachment in row.attachments:
        if attachment.skipped:
            skipped += 1
        elif (attachment.mime or "").lower().startswith("application/pdf") or attachment.filename.lower().endswith(
            ".pdf"
        ):
            pdfs += 1
    return QueueItemOut(
        id=str(row.id),
        sender=row.sender,
        subject=row.subject,
        status=row.status,
        sent_at=row.sent_at.isoformat() if row.sent_at else None,
        snippet=row.snippet or "",
        pdf_count=pdfs,
        skipped_attachment_count=skipped,
        summary=row.summary,
        relevant=row.relevant,
        needs_human_review=bool(row.needs_human_review),
        classifications=[
            ClassificationOut(category=item.category, confidence=item.confidence, reason=item.reason)
            for item in sorted(row.classifications or [], key=lambda item: item.category)
        ],
    )


@router.get("", response_model=QueueListOut)
def list_messages(
    user: CurrentUser,
    db: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> QueueListOut:
    if status_filter and status_filter not in QUEUE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Status must be pending, processing, ready, or reviewed.",
        )
    stmt = (
        select(Message)
        .options(selectinload(Message.attachments), selectinload(Message.classifications))
        .where(Message.user_id == user.id)
    )
    if status_filter:
        stmt = stmt.where(Message.status == status_filter)
    rows = db.scalars(
        stmt.order_by(Message.sent_at.desc().nullslast(), Message.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return QueueListOut(
        items=[_item_out(row) for row in rows],
        counts=_counts_for(db, user.id),
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/{message_id}", response_model=QueueDetailOut)
def get_message(message_id: str, user: CurrentUser, db: DbSession) -> QueueDetailOut:
    row = db.scalar(
        select(Message)
        .options(
            selectinload(Message.attachments),
            selectinload(Message.classifications),
            selectinload(Message.extracted_fields),
        )
        .where(Message.id == message_id, Message.user_id == user.id)
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    base = _item_out(row)
    return QueueDetailOut(
        **base.model_dump(),
        body=row.body,
        body_html=row.body_html,
        gmail_message_id=row.gmail_message_id,
        attachments=[
            QueueAttachmentOut(
                id=str(item.id),
                filename=item.filename,
                mime=item.mime,
                skipped=item.skipped,
                skip_reason=item.skip_reason,
                size_bytes=item.size_bytes,
                processed=item.processed,
                page_count=item.page_count,
                document_flavor=item.document_flavor,
                duration_ms=item.duration_ms,
                extract_error=item.extract_error,
            )
            for item in row.attachments
        ],
        extracted_fields=[
            ExtractedFieldOut(
                field=item.field,
                value=item.value,
                confidence=item.confidence,
                source_type=item.source_type,
                source_id=item.source_id,
                source_quote=item.source_quote,
                source_page=item.source_page,
                source_ref=item.source_ref,
            )
            for item in sorted(row.extracted_fields, key=lambda item: item.field)
        ],
        relevance_reason=row.relevance_reason,
        ai_model=row.ai_model,
        ai_prompt_version=row.ai_prompt_version,
    )


def _page_out(page: PdfPage) -> PdfPageOut:
    return PdfPageOut(
        id=str(page.id),
        page_number=page.page_number,
        text=page.text or "",
        original_text=page.original_text or "",
        translated_text=page.translated_text,
        language=page.language,
        language_confidence=page.language_confidence,
        ocr_confidence=page.ocr_confidence,
        llm_score=page.llm_score,
        flavor=page.flavor,
        extract_method=page.extract_method,
        column_count=page.column_count,
        tables=page.tables or [],
        image_notes=page.image_notes or [],
        needs_human_review=bool(page.needs_human_review),
        review_reasons=page.review_reasons or [],
        source_ref=page.source_ref,
    )


@router.get("/{message_id}/attachments/{attachment_id}/pages", response_model=PdfPagesOut)
def get_attachment_pages(
    message_id: str,
    attachment_id: str,
    user: CurrentUser,
    db: DbSession,
) -> PdfPagesOut:
    attachment = db.scalar(
        select(Attachment)
        .options(selectinload(Attachment.pages), selectinload(Attachment.message))
        .where(Attachment.id == attachment_id)
    )
    if attachment is None or attachment.message is None or attachment.message_id != message_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    if attachment.message.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    pages = sorted(attachment.pages, key=lambda item: item.page_number)
    return PdfPagesOut(
        attachment_id=str(attachment.id),
        filename=attachment.filename,
        document_flavor=attachment.document_flavor,
        processed=attachment.processed,
        page_count=attachment.page_count if attachment.page_count is not None else len(pages),
        duration_ms=attachment.duration_ms,
        extract_error=attachment.extract_error,
        pages=[_page_out(page) for page in pages],
    )
