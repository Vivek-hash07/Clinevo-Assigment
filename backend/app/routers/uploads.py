"""Local fixture load and PDF upload (outside Gmail)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.constants import SOURCE_FIXTURE
from app.deps import CurrentUser, DbSession
from app.models import Message
from app.schemas import FixtureCoverageOut, FixtureLoadOut, FixtureLoadRequest, UploadOut
from app.services.audit import write_audit
from app.services.local_ingest import LocalIngestError, enqueue_message_pipeline, ingest_uploads, load_fixture_messages
from app.services.synthetic import (
    batch_keys,
    catalog_coverage,
    required_coverage_ok,
    send_synthetic_mailbox,
    synthetic_catalog,
)

router = APIRouter(tags=["fixtures"])
logger = logging.getLogger(__name__)


def _enqueue_or_503(user_id: str, message: Message) -> list[str]:
    try:
        return enqueue_message_pipeline(user_id, message)
    except Exception:
        logger.exception("Failed to enqueue pipeline for %s", message.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The document was saved but could not be added to the processing queue. "
                "The database may be unreachable — retry from the queue in a moment."
            ),
        ) from None


@router.get("/api/fixtures/coverage", response_model=FixtureCoverageOut)
def fixture_coverage(user: CurrentUser, db: DbSession) -> FixtureCoverageOut:
    coverage = catalog_coverage()
    loaded = list(
        db.scalars(select(Message.fixture_key).where(Message.user_id == user.id, Message.fixture_key.is_not(None)))
    )
    return FixtureCoverageOut(
        **coverage,
        meets_day6=required_coverage_ok(coverage),
        loaded_keys=[key for key in loaded if key],
        templates=[item.key for item in synthetic_catalog()],
    )


@router.post("/api/fixtures/load", response_model=FixtureLoadOut)
def load_fixtures(
    user: CurrentUser,
    db: DbSession,
    body: FixtureLoadRequest | None = None,
) -> FixtureLoadOut:
    """Assignment Day 6 path: put synthetic emails in the queue. No mailbox sync.

    Optional email_copy uses SMTP (Amazon Mail Manager) to send the same dummy
    messages to the signed-in user. The queue does not wait for those to be read back.
    """
    payload = body or FixtureLoadRequest()
    keys = batch_keys() if payload.batch else [item.key for item in synthetic_catalog()]
    try:
        rows = load_fixture_messages(db, user, keys, source=SOURCE_FIXTURE)
        db.commit()
    except LocalIngestError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    queued: list[str] = []
    for row in rows:
        if row.status in {"ready", "reviewed"}:
            continue
        queued.extend(_enqueue_or_503(str(user.id), row))

    emailed_count = 0
    emailed_to: str | None = None
    email_note = ""
    if payload.email_copy:
        try:
            result = send_synthetic_mailbox(user.email, keys)
            emailed_count = int(result["count"])
            emailed_to = str(result["to"])
            write_audit(
                db,
                "mail.synthetic_copy_sent",
                user.id,
                {"to": emailed_to, "count": emailed_count, "keys": keys},
            )
            db.commit()
            email_note = f" SMTP also sent {emailed_count} copy(ies) to {emailed_to}."
        except Exception:
            logger.exception("SMTP copy of dummy emails failed for %s", user.email)
            email_note = (
                " The reviewer queue is loaded. SMTP could not send a copy — "
                "check SMTP_* on the API host."
            )

    return FixtureLoadOut(
        ok=True,
        queued=bool(queued),
        count=len(rows),
        message_ids=[str(row.id) for row in rows],
        keys=[str(row.fixture_key or "") for row in rows],
        queued_event_ids=queued,
        emailed_count=emailed_count,
        emailed_to=emailed_to,
        message=(
            f"Loaded {len(rows)} synthetic sample emails and queued {len(queued)} job(s). "
            "No mailbox sync is required."
            f"{email_note}"
        ),
    )


@router.post("/api/uploads", response_model=UploadOut)
async def upload_pdfs(
    user: CurrentUser,
    db: DbSession,
    files: list[UploadFile] = File(...),
    subject: str | None = Form(default=None),
    note: str | None = Form(default=None),
) -> UploadOut:
    blobs: list[tuple[str, bytes]] = []
    for item in files:
        filename = item.filename or "upload.pdf"
        data = await item.read()
        blobs.append((filename, data))
    try:
        message = ingest_uploads(db, user, blobs, subject=subject, note=note)
        db.commit()
        db.refresh(message)
    except LocalIngestError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception:
        db.rollback()
        logger.exception("PDF upload failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The PDF could not be saved. Check the API logs and try again.",
        ) from None
    event_ids = _enqueue_or_503(str(user.id), message)
    names = ", ".join(name for name, _ in blobs[:3])
    extra = f" and {len(blobs) - 3} more" if len(blobs) > 3 else ""
    return UploadOut(
        ok=True,
        queued=bool(event_ids),
        message_id=str(message.id),
        queued_event_ids=event_ids,
        message=(
            f"Saved {names}{extra}. The in-process worker is extracting text, classifying, "
            "and extracting facts — open the new queue item when its status is ready."
        ),
    )
