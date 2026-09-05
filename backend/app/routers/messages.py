from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import Message

router = APIRouter(prefix="/api/messages", tags=["messages"])


class QueueItemOut(BaseModel):
    id: str
    sender: str
    subject: str
    status: str
    sent_at: str | None


@router.get("", response_model=list[QueueItemOut])
def list_messages(user: CurrentUser, db: DbSession) -> list[QueueItemOut]:
    rows = db.scalars(
        select(Message).where(Message.user_id == user.id).order_by(Message.created_at.desc())
    ).all()
    return [
        QueueItemOut(
            id=str(row.id),
            sender=row.sender,
            subject=row.subject,
            status=row.status,
            sent_at=row.sent_at.isoformat() if row.sent_at else None,
        )
        for row in rows
    ]
