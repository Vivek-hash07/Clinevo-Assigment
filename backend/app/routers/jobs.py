"""Pipeline observability.

Replaces the Inngest dashboard: the reviewer UI reads this to show which stage each
document is in, how long each stage took, and what failed.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import CurrentUser
from app.jobqueue import store as queue_store
from app.jobqueue.registry import all_specs, get_handler
from app.jobqueue.worker import current_worker
from app.schemas import JobOut, QueueHealthOut

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _to_job_out(row: dict) -> JobOut:
    spec = get_handler(str(row["kind"]))
    return JobOut(
        id=str(row["id"]),
        kind=str(row["kind"]),
        label=spec.label if spec else str(row["kind"]),
        status=str(row["status"]),
        attempts=int(row["attempts"] or 0),
        max_attempts=int(row["max_attempts"] or 0),
        message_id=str(row["message_id"]) if row.get("message_id") else None,
        created_at=_iso(row.get("created_at")),
        started_at=_iso(row.get("started_at")),
        finished_at=_iso(row.get("finished_at")),
        duration_ms=row.get("duration_ms"),
        last_error=row.get("last_error"),
    )


@router.get("", response_model=QueueHealthOut)
def list_jobs(
    user: CurrentUser,
    limit: int = Query(default=40, ge=1, le=200),
) -> QueueHealthOut:
    worker = current_worker()
    stats = worker.stats() if worker else {}
    rows = queue_store.recent_jobs(user_id=str(user.id), limit=limit)
    return QueueHealthOut(
        worker_running=bool(stats.get("running")),
        concurrency=int(stats.get("concurrency") or 0),
        processed=int(stats.get("processed") or 0),
        failed=int(stats.get("failed") or 0),
        uptime_seconds=int(stats.get("uptime_seconds") or 0),
        mailbox_poll_seconds=int(stats.get("mailbox_poll_seconds") or 0),
        counts=queue_store.counts_by_status(user_id=str(user.id)),
        jobs=[_to_job_out(row) for row in rows],
    )


@router.get("/stages")
def list_stages(user: CurrentUser) -> dict:
    """The pipeline definition, so the UI can render the DAG without hardcoding it."""
    return {
        "stages": [
            {"kind": spec.kind, "label": spec.label, "max_attempts": spec.max_attempts}
            for spec in all_specs()
        ]
    }
