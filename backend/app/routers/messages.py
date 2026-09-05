from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload

from app.constants import QUEUE_STATUSES
from app.deps import CurrentUser, DbSession
from app.models import Attachment, AuditEvent, ExtractedField, Message, PdfPage, PipelineRun, Review
from app.schemas import (
    AuditEventOut,
    ClassificationOut,
    ExtractedFieldOut,
    FieldGroupOut,
    PdfPageOut,
    PdfPagesOut,
    PipelineRunOut,
    QueueAttachmentOut,
    QueueCounts,
    QueueDetailOut,
    QueueItemOut,
    QueueListOut,
    ReviewOut,
    ReviewRequest,
)
from app.services.review import (
    ReviewError,
    apply_review,
    can_review_status,
    field_label,
    grouped_fields,
    latest_field_reviews,
)
from app.services.storage import read_bytes

router = APIRouter(prefix="/api/messages", tags=["messages"])

_MESSAGE_DETAIL_OPTIONS = (
    selectinload(Message.attachments),
    selectinload(Message.classifications),
    selectinload(Message.extracted_fields),
    selectinload(Message.reviews),
)


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


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _pdf_count(row: Message) -> tuple[int, int]:
    pdfs = 0
    skipped = 0
    for attachment in row.attachments:
        if attachment.skipped:
            skipped += 1
        elif (attachment.mime or "").lower().startswith("application/pdf") or attachment.filename.lower().endswith(
            ".pdf"
        ):
            pdfs += 1
    return pdfs, skipped


def _attachment_error(row: Message) -> str | None:
    for attachment in row.attachments:
        if attachment.extract_error:
            return attachment.extract_error
    return None


def _pipeline_metrics(db: DbSession, message_ids: list[str]) -> dict[str, tuple[int | None, str | None]]:
    if not message_ids:
        return {}
    rows = db.execute(
        select(
            PipelineRun.message_id,
            func.sum(PipelineRun.duration_ms),
            func.sum(case((PipelineRun.status == "failed", 1), else_=0)),
        )
        .where(PipelineRun.message_id.in_(message_ids))
        .group_by(PipelineRun.message_id)
    ).all()
    out: dict[str, tuple[int | None, str | None]] = {}
    for message_id, duration, failed in rows:
        duration_ms = int(duration) if duration is not None else None
        error = "AI pipeline failed. Sync again to retry this message." if int(failed or 0) else None
        out[str(message_id)] = (duration_ms, error)
    return out


def _item_out(row: Message, duration_ms: int | None = None, last_error: str | None = None) -> QueueItemOut:
    pdfs, skipped = _pdf_count(row)
    if duration_ms is None:
        durations = [item.duration_ms for item in row.attachments if item.duration_ms is not None]
        duration_ms = sum(durations) if durations else None
    error = last_error or _attachment_error(row)
    return QueueItemOut(
        id=str(row.id),
        sender=row.sender,
        subject=row.subject,
        status=row.status,
        sent_at=_iso(row.sent_at),
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
        duration_ms=duration_ms,
        last_error=error,
    )


def _field_out(item: ExtractedField, review: Review | None) -> ExtractedFieldOut:
    return ExtractedFieldOut(
        id=str(item.id),
        field=item.field,
        label=field_label(item.field),
        value=item.value,
        confidence=item.confidence,
        source_type=item.source_type,
        source_id=item.source_id,
        source_quote=item.source_quote,
        source_page=item.source_page,
        source_ref=item.source_ref,
        locked=review is not None,
        review_action=review.action if review else None,
        review_reason=review.reason if review else None,
        reviewed_at=_iso(review.created_at) if review else None,
    )


def _load_message(db: DbSession, message_id: str, user_id: str) -> Message | None:
    return db.scalar(
        select(Message)
        .options(*_MESSAGE_DETAIL_OPTIONS)
        .where(Message.id == message_id, Message.user_id == user_id)
    )


def _detail_out(db: DbSession, row: Message) -> QueueDetailOut:
    metrics = _pipeline_metrics(db, [row.id])
    duration_ms, pipeline_error = metrics.get(row.id, (None, None))
    base = _item_out(row, duration_ms=duration_ms, last_error=pipeline_error)
    locked = latest_field_reviews(list(row.reviews or []))
    by_name = {item.field: _field_out(item, locked.get(item.field)) for item in row.extracted_fields}
    field_outs = [by_name[name] for name in sorted(by_name)]
    groups = [
        FieldGroupOut(id=group_id, title=title, fields=[by_name[item.field] for item in items])
        for group_id, title, items in grouped_fields(list(row.extracted_fields))
    ]
    runs = db.scalars(
        select(PipelineRun)
        .where(PipelineRun.message_id == row.id)
        .order_by(PipelineRun.started_at.asc().nullslast(), PipelineRun.created_at.asc())
    ).all()
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.message_id == row.id)
        .order_by(AuditEvent.created_at.asc())
        .limit(100)
    ).all()
    reviews = sorted(row.reviews or [], key=lambda item: item.created_at)
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
                has_file=bool(item.storage_key) and not item.skipped,
            )
            for item in row.attachments
        ],
        extracted_fields=field_outs,
        field_groups=groups,
        reviews=[
            ReviewOut(
                id=str(item.id),
                action=item.action,
                field_name=item.field_name,
                old_value=item.old_value,
                new_value=item.new_value,
                reason=item.reason,
                user_id=item.user_id,
                created_at=item.created_at.isoformat(),
            )
            for item in reviews
        ],
        audit_events=[
            AuditEventOut(
                id=str(item.id),
                event_type=item.event_type,
                payload=item.payload or {},
                created_at=item.created_at.isoformat(),
            )
            for item in events
        ],
        pipeline_runs=[
            PipelineRunOut(
                id=str(item.id),
                function_name=item.function_name,
                status=item.status,
                duration_ms=item.duration_ms,
                model=item.model,
                prompt_version=item.prompt_version,
                started_at=_iso(item.started_at),
                finished_at=_iso(item.finished_at),
            )
            for item in runs
        ],
        relevance_reason=row.relevance_reason,
        ai_model=row.ai_model,
        ai_prompt_version=row.ai_prompt_version,
        ai_completed_at=_iso(row.ai_completed_at),
        can_review=can_review_status(row.status),
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
    metrics = _pipeline_metrics(db, [row.id for row in rows])
    items = []
    for row in rows:
        duration_ms, pipeline_error = metrics.get(row.id, (None, None))
        items.append(_item_out(row, duration_ms=duration_ms, last_error=pipeline_error))
    return QueueListOut(
        items=items,
        counts=_counts_for(db, user.id),
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/{message_id}", response_model=QueueDetailOut)
def get_message(message_id: str, user: CurrentUser, db: DbSession) -> QueueDetailOut:
    row = _load_message(db, message_id, user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return _detail_out(db, row)


@router.post("/{message_id}/reviews", response_model=QueueDetailOut)
def review_message(message_id: str, body: ReviewRequest, user: CurrentUser, db: DbSession) -> QueueDetailOut:
    row = _load_message(db, message_id, user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    try:
        apply_review(db, user, row, body)
        db.commit()
    except ReviewError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    row = _load_message(db, message_id, user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return _detail_out(db, row)


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


def _owned_attachment(db: DbSession, message_id: str, attachment_id: str, user_id: str) -> Attachment:
    attachment = db.scalar(
        select(Attachment)
        .options(selectinload(Attachment.pages), selectinload(Attachment.message))
        .where(Attachment.id == attachment_id)
    )
    if attachment is None or attachment.message is None or attachment.message_id != message_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    if attachment.message.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    return attachment


@router.get("/{message_id}/attachments/{attachment_id}/pages", response_model=PdfPagesOut)
def get_attachment_pages(
    message_id: str,
    attachment_id: str,
    user: CurrentUser,
    db: DbSession,
) -> PdfPagesOut:
    attachment = _owned_attachment(db, message_id, attachment_id, user.id)
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


def _safe_filename(name: str) -> str:
    raw = (name or "attachment.pdf").replace("\r", "").replace("\n", " ").replace('"', "")
    base = raw.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip() or "attachment.pdf"
    return base[:180]


@router.get("/{message_id}/attachments/{attachment_id}/file")
def get_attachment_file(
    message_id: str,
    attachment_id: str,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    attachment = _owned_attachment(db, message_id, attachment_id, user.id)
    if attachment.skipped or not attachment.storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF file is not available")
    mime = (attachment.mime or "").lower()
    if not (mime.startswith("application/pdf") or attachment.filename.lower().endswith(".pdf")):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Not a PDF attachment")
    try:
        data = read_bytes(attachment.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF file is not stored") from exc
    filename = _safe_filename(attachment.filename)
    ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "attachment.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(len(data)),
        },
    )
