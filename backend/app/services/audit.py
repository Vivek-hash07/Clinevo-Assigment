from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent


def write_audit(
    db: Session,
    event_type: str,
    user_id: str | None = None,
    payload: dict[str, Any] | None = None,
    message_id: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            event_type=event_type,
            user_id=user_id,
            message_id=message_id,
            payload=payload or {},
        )
    )
