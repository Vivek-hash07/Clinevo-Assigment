"""Human-in-the-loop accept / override. AI never silently overwrites locked fields."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.constants import (
    FIELD_GROUPS,
    FIELD_LABELS,
    OVERRIDE_REASON_MIN_CHARS,
    REVIEW_ACTION_ACCEPT,
    REVIEW_ACTION_COMPLETE,
    REVIEW_ACTION_OVERRIDE,
    REVIEW_LOCK_ACTIONS,
    REVIEW_REASON_MAX_CHARS,
    REVIEW_VALUE_MAX_CHARS,
    STATUS_READY,
    STATUS_REVIEWED,
)
from app.models import ExtractedField, Message, Review, User
from app.schemas import ReviewRequest
from app.services.audit import write_audit

REVIEWABLE_STATUSES = frozenset({STATUS_READY, STATUS_REVIEWED})


class ReviewError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class ValidatedReview:
    action: str
    field: str | None
    value: str | None
    reason: str | None


def field_label(name: str) -> str:
    if name in FIELD_LABELS:
        return FIELD_LABELS[name]
    parts = [part.replace("_", " ") for part in name.split(".") if part]
    return " · ".join(part.capitalize() for part in parts) or name


def latest_field_reviews(reviews: list[Review]) -> dict[str, Review]:
    latest: dict[str, Review] = {}
    for row in sorted(reviews, key=lambda item: item.created_at):
        if row.action in REVIEW_LOCK_ACTIONS and row.field_name:
            latest[row.field_name] = row
    return latest


def can_review_status(status: str) -> bool:
    return status in REVIEWABLE_STATUSES


def validate_review_payload(req: ReviewRequest, current_value: str | None = None) -> ValidatedReview:
    action = req.action
    field = (req.field or "").strip() or None
    value = req.value.strip() if isinstance(req.value, str) else req.value
    if isinstance(value, str):
        value = value.strip() or None
    reason = req.reason.strip() if isinstance(req.reason, str) else req.reason
    if isinstance(reason, str):
        reason = reason.strip() or None

    if action == REVIEW_ACTION_COMPLETE:
        if field or value:
            raise ReviewError("Complete review does not take a field or value.")
        return ValidatedReview(action=action, field=None, value=None, reason=reason)

    if not field:
        raise ReviewError("Field is required for accept and override.")
    if len(field) > 128:
        raise ReviewError("Field name is too long.")

    if action == REVIEW_ACTION_ACCEPT:
        return ValidatedReview(action=action, field=field, value=None, reason=reason)

    if action != REVIEW_ACTION_OVERRIDE:
        raise ReviewError("Action must be accept, override, or complete.")

    if not reason or len(reason) < OVERRIDE_REASON_MIN_CHARS:
        raise ReviewError(
            f"Override reason is required ({OVERRIDE_REASON_MIN_CHARS} or more characters)."
        )
    if len(reason) > REVIEW_REASON_MAX_CHARS:
        raise ReviewError("Override reason is too long.")
    if not value:
        raise ReviewError("Override value is required.")
    if len(value) > REVIEW_VALUE_MAX_CHARS:
        raise ReviewError("Override value is too long.")
    if current_value is not None and value == current_value.strip():
        raise ReviewError("Override value must differ from the current value.")
    return ValidatedReview(action=action, field=field, value=value, reason=reason)


def apply_review(db: Session, user: User, message: Message, req: ReviewRequest) -> Message:
    if not can_review_status(message.status):
        raise ReviewError("This message is not ready for review yet.", 409)

    if req.action == REVIEW_ACTION_COMPLETE:
        validated = validate_review_payload(req)
        return _complete_review(db, user, message, validated.reason)

    field_row = None
    if req.field:
        field_row = next((item for item in message.extracted_fields if item.field == req.field.strip()), None)
        if field_row is None:
            raise ReviewError("Unknown field.", 404)

    validated = validate_review_payload(req, current_value=field_row.value if field_row else None)
    assert validated.field is not None
    assert field_row is not None

    old_value = field_row.value
    new_value = old_value if validated.action == REVIEW_ACTION_ACCEPT else validated.value
    assert new_value is not None

    if validated.action == REVIEW_ACTION_OVERRIDE:
        field_row.value = new_value

    db.add(
        Review(
            message_id=message.id,
            user_id=user.id,
            action=validated.action,
            field_name=validated.field,
            old_value=old_value,
            new_value=new_value,
            reason=validated.reason,
        )
    )
    event_type = "review.accepted" if validated.action == REVIEW_ACTION_ACCEPT else "review.overridden"
    write_audit(
        db,
        event_type,
        user.id,
        {
            "field": validated.field,
            "label": field_label(validated.field),
            "old_value": old_value,
            "new_value": new_value,
            "reason": validated.reason,
            "actor_email": user.email,
            "actor_name": user.name,
        },
        message_id=message.id,
    )
    return message


def _complete_review(db: Session, user: User, message: Message, reason: str | None) -> Message:
    locked = latest_field_reviews(list(message.reviews))
    accepted: list[str] = []
    for field_row in message.extracted_fields:
        if field_row.field in locked:
            continue
        db.add(
            Review(
                message_id=message.id,
                user_id=user.id,
                action=REVIEW_ACTION_ACCEPT,
                field_name=field_row.field,
                old_value=field_row.value,
                new_value=field_row.value,
                reason=reason,
            )
        )
        accepted.append(field_row.field)

    message.status = STATUS_REVIEWED
    write_audit(
        db,
        "review.completed",
        user.id,
        {
            "accepted_fields": accepted,
            "already_reviewed": sorted(locked),
            "reason": reason,
            "actor_email": user.email,
            "actor_name": user.name,
        },
        message_id=message.id,
    )
    return message


def grouped_fields(fields: list[ExtractedField]) -> list[tuple[str, str, list[ExtractedField]]]:
    by_name = {item.field: item for item in fields}
    used: set[str] = set()
    groups: list[tuple[str, str, list[ExtractedField]]] = []
    for group_id, title, catalog in FIELD_GROUPS:
        rows = [by_name[name] for name in catalog if name in by_name]
        if not rows:
            continue
        used.update(item.field for item in rows)
        groups.append((group_id, title, rows))
    leftover = sorted((item for item in fields if item.field not in used), key=lambda item: item.field)
    if leftover:
        groups.append(("other", "Other", leftover))
    return groups
