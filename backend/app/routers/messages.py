from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.constants import QUEUE_STATUSES
from app.deps import CurrentUser, DbSession
from app.models import Message
from app.schemas import QueueAttachmentOut, QueueCounts, QueueDetailOut, QueueItemOut, QueueListOut

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
        .options(selectinload(Message.attachments))
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
        .options(selectinload(Message.attachments))
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
            )
            for item in row.attachments
        ],
    )
