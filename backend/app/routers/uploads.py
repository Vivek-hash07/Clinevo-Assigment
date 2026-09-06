"""Local fixture load and PDF upload (outside Gmail)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.constants import SOURCE_FIXTURE
from app.deps import CurrentUser, DbSession
from app.models import Message
from app.schemas import FixtureCoverageOut, FixtureLoadOut, UploadOut
from app.services.local_ingest import LocalIngestError, enqueue_message_pipeline, ingest_uploads, load_fixture_messages
from app.services.synthetic import (
    batch_keys,
    catalog_coverage,
    required_coverage_ok,
    synthetic_catalog,
)

router = APIRouter(tags=["fixtures"])
logger = logging.getLogger(__name__)


def _enqueue_or_503(user_id: str, message: Message, *, retry: bool = False) -> list[str]:
    try:
        return enqueue_message_pipeline(user_id, message, retry=retry)
    except Exception:
        logger.exception("Failed to enqueue pipeline for %s", message.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The document was saved but the pipeline could not be queued. "
                "Start the Inngest Dev Server (npx inngest-cli@latest dev -u "
                "http://localhost:8080/api/inngest) and try again."
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
def load_fixtures(user: CurrentUser, db: DbSession, batch: bool = True) -> FixtureLoadOut:
    keys = batch_keys() if batch else [item.key for item in synthetic_catalog()]
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
        queued.extend(_enqueue_or_503(str(user.id), row, retry=True))
    return FixtureLoadOut(
        ok=True,
        queued=bool(queued),
        count=len(rows),
        message_ids=[str(row.id) for row in rows],
        keys=[str(row.fixture_key or "") for row in rows],
        queued_event_ids=queued,
        message=(
            f"Loaded {len(rows)} synthetic messages into the reviewer queue and queued the Inngest pipeline. "
            "This path does not use Gmail."
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
    event_ids = _enqueue_or_503(str(user.id), message)
    return UploadOut(
        ok=True,
        queued=True,
        message_id=str(message.id),
        queued_event_ids=event_ids,
        message="PDF uploaded. It will appear in the same reviewer queue when the pipeline finishes.",
    )
