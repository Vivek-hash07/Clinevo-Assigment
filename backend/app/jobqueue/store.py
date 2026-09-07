"""Postgres-backed queue storage.

Claims use `FOR UPDATE SKIP LOCKED`, so several worker threads — or several API
instances — can share one queue table without handing the same job out twice.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.database import session_scope
from app.jobqueue.types import (
    ACTIVE_STATUSES,
    DEFAULT_MAX_ATTEMPTS,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SKIPPED,
    STATUS_SUCCEEDED,
    ClaimedJob,
    JobEvent,
)

logger = logging.getLogger(__name__)

RETRY_BASE_SECONDS = 5.0
RETRY_MAX_SECONDS = 300.0


def _retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter, so a batch of failures does not retry in lockstep."""
    delay = min(RETRY_BASE_SECONDS * (2 ** max(attempt - 1, 0)), RETRY_MAX_SECONDS)
    return delay * random.uniform(0.7, 1.3)


_INSERT_SQL = text(
    """
    INSERT INTO queue_jobs (
        id, kind, idempotency_key, user_id, message_id, payload,
        status, attempts, max_attempts, priority, run_after,
        parent_job_id, created_at, updated_at
    )
    VALUES (
        gen_random_uuid()::text, :kind, :idempotency_key, :user_id, :message_id, CAST(:payload AS jsonb),
        'queued', 0, :max_attempts, :priority, now() + (:delay_seconds * interval '1 second'),
        :parent_job_id, now(), now()
    )
    ON CONFLICT DO NOTHING
    RETURNING id
    """
)


def enqueue(events: list[JobEvent] | JobEvent, *, parent_job_id: str | None = None) -> list[str]:
    """Write jobs to the queue. Returns the ids actually created; an event whose
    idempotency key already has a live job is silently skipped."""
    with session_scope() as db:
        return enqueue_in_session(db, events, parent_job_id=parent_job_id)


def enqueue_in_session(db, events: list[JobEvent] | JobEvent, *, parent_job_id: str | None = None) -> list[str]:
    items = [events] if isinstance(events, JobEvent) else list(events)
    created: list[str] = []
    for event in items:
        job_id = db.execute(
            _INSERT_SQL,
            {
                "kind": event.kind,
                "idempotency_key": event.idempotency_key,
                "user_id": event.user_id,
                "message_id": event.message_id,
                "payload": json.dumps(event.payload or {}),
                "max_attempts": event.max_attempts or DEFAULT_MAX_ATTEMPTS,
                "priority": event.priority,
                "delay_seconds": max(event.delay_seconds, 0.0),
                "parent_job_id": parent_job_id,
            },
        ).scalar()
        if job_id:
            created.append(str(job_id))
        else:
            logger.debug("queue: deduplicated %s (%s)", event.kind, event.idempotency_key)
    return created


_CLAIM_SQL = text(
    """
    UPDATE queue_jobs SET
        status = 'running',
        attempts = attempts + 1,
        locked_by = :worker_id,
        locked_at = now(),
        started_at = COALESCE(started_at, now()),
        updated_at = now()
    WHERE id = (
        SELECT id FROM queue_jobs
        WHERE status = 'queued' AND run_after <= now()
        ORDER BY priority DESC, run_after, created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, kind, payload, attempts, max_attempts, user_id, message_id
    """
)


def claim_next(worker_id: str) -> ClaimedJob | None:
    with session_scope() as db:
        row = db.execute(_CLAIM_SQL, {"worker_id": worker_id}).mappings().first()
        if row is None:
            return None
        return ClaimedJob(
            id=str(row["id"]),
            kind=str(row["kind"]),
            payload=dict(row["payload"] or {}),
            attempt=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            user_id=row["user_id"],
            message_id=row["message_id"],
        )


def complete(
    job_id: str,
    *,
    result: dict[str, Any] | None = None,
    follow_ups: list[JobEvent] | None = None,
    skipped: bool = False,
) -> list[str]:
    """Mark a job done and enqueue its follow-ups atomically, so the pipeline can never
    lose a hand-off between two steps."""
    status = STATUS_SKIPPED if skipped else STATUS_SUCCEEDED
    with session_scope() as db:
        db.execute(
            text(
                """
                UPDATE queue_jobs SET
                    status = :status,
                    finished_at = now(),
                    duration_ms = GREATEST(
                        0, EXTRACT(EPOCH FROM (now() - COALESCE(started_at, created_at))) * 1000
                    )::int,
                    result = CAST(:result AS jsonb),
                    last_error = NULL,
                    locked_by = NULL,
                    locked_at = NULL,
                    updated_at = now()
                WHERE id = :job_id
                """
            ),
            {"job_id": job_id, "status": status, "result": json.dumps(_jsonable(result or {}))},
        )
        if follow_ups:
            return enqueue_in_session(db, follow_ups, parent_job_id=job_id)
        return []


def fail(job_id: str, error: str, *, retriable: bool = True) -> str:
    """Reschedule with backoff, or mark failed once attempts are exhausted."""
    with session_scope() as db:
        row = db.execute(
            text("SELECT attempts, max_attempts FROM queue_jobs WHERE id = :job_id"),
            {"job_id": job_id},
        ).mappings().first()
        if row is None:
            return STATUS_FAILED
        attempts = int(row["attempts"])
        max_attempts = int(row["max_attempts"])
        give_up = (not retriable) or attempts >= max_attempts
        if give_up:
            db.execute(
                text(
                    """
                    UPDATE queue_jobs SET
                        status = 'failed',
                        finished_at = now(),
                        duration_ms = GREATEST(
                            0, EXTRACT(EPOCH FROM (now() - COALESCE(started_at, created_at))) * 1000
                        )::int,
                        last_error = :error,
                        locked_by = NULL,
                        locked_at = NULL,
                        updated_at = now()
                    WHERE id = :job_id
                    """
                ),
                {"job_id": job_id, "error": error[:4000]},
            )
            return STATUS_FAILED
        db.execute(
            text(
                """
                UPDATE queue_jobs SET
                    status = 'queued',
                    run_after = now() + (:delay * interval '1 second'),
                    last_error = :error,
                    locked_by = NULL,
                    locked_at = NULL,
                    updated_at = now()
                WHERE id = :job_id
                """
            ),
            {"job_id": job_id, "error": error[:4000], "delay": _retry_delay(attempts)},
        )
        return STATUS_QUEUED


def reclaim_stale(lease_seconds: int) -> int:
    """Requeue jobs whose worker died mid-run. `attempts` was already incremented at
    claim time, so a job that keeps killing its worker still exhausts its retries."""
    with session_scope() as db:
        result = db.execute(
            text(
                """
                UPDATE queue_jobs SET
                    status = 'queued',
                    run_after = now(),
                    locked_by = NULL,
                    locked_at = NULL,
                    last_error = COALESCE(last_error, 'worker lease expired'),
                    updated_at = now()
                WHERE status = 'running'
                  AND locked_at IS NOT NULL
                  AND locked_at < now() - (:lease * interval '1 second')
                """
            ),
            {"lease": lease_seconds},
        )
        return int(result.rowcount or 0)


def purge_finished(older_than_days: int) -> int:
    with session_scope() as db:
        result = db.execute(
            text(
                "DELETE FROM queue_jobs WHERE status IN ('succeeded', 'skipped') "
                "AND finished_at < now() - (:days * interval '1 day')"
            ),
            {"days": older_than_days},
        )
        return int(result.rowcount or 0)


def counts_by_status(user_id: str | None = None) -> dict[str, int]:
    with session_scope() as db:
        sql = "SELECT status, count(*) AS n FROM queue_jobs"
        params: dict[str, Any] = {}
        if user_id:
            sql += " WHERE user_id = :user_id"
            params["user_id"] = user_id
        sql += " GROUP BY status"
        rows = db.execute(text(sql), params).mappings().all()
        return {str(row["status"]): int(row["n"]) for row in rows}


def recent_jobs(user_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with session_scope() as db:
        sql = (
            "SELECT id, kind, status, attempts, max_attempts, message_id, "
            "created_at, started_at, finished_at, duration_ms, last_error, run_after "
            "FROM queue_jobs"
        )
        params: dict[str, Any] = {"limit": max(1, min(limit, 200))}
        if user_id:
            sql += " WHERE user_id = :user_id"
            params["user_id"] = user_id
        sql += " ORDER BY created_at DESC LIMIT :limit"
        rows = db.execute(text(sql), params).mappings().all()
        return [dict(row) for row in rows]


def pending_for_message(message_id: str) -> int:
    with session_scope() as db:
        return int(
            db.execute(
                text(
                    "SELECT count(*) FROM queue_jobs "
                    "WHERE message_id = :message_id AND status IN ('queued', 'running')"
                ),
                {"message_id": message_id},
            ).scalar()
            or 0
        )


def _jsonable(value: Any) -> Any:
    """Pipeline steps return plain dicts, but a few carry datetimes through."""
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def stale_cutoff(lease_seconds: int) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=lease_seconds)


__all__ = [
    "ACTIVE_STATUSES",
    "STATUS_FAILED",
    "STATUS_QUEUED",
    "STATUS_RUNNING",
    "STATUS_SKIPPED",
    "STATUS_SUCCEEDED",
    "claim_next",
    "complete",
    "counts_by_status",
    "enqueue",
    "enqueue_in_session",
    "fail",
    "pending_for_message",
    "purge_finished",
    "recent_jobs",
    "reclaim_stale",
    "stale_cutoff",
]
