"""Core queue vocabulary: events, handler context, and error semantics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_MAX_ATTEMPTS = 3

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING)
TERMINAL_STATUSES = (STATUS_SUCCEEDED, STATUS_FAILED, STATUS_SKIPPED)


class NonRetriableError(Exception):
    """Raised by a handler when the job can never succeed, so retrying is pointless."""


class MissingPayload(NonRetriableError):
    """A required payload key was absent. A retry would hit the same bad payload."""


@dataclass
class JobEvent:
    """A job waiting to be written to the queue."""

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    user_id: str | None = None
    message_id: str | None = None
    delay_seconds: float = 0.0
    max_attempts: int | None = None
    priority: int = 0


@dataclass
class ClaimedJob:
    """A job this worker has exclusively leased."""

    id: str
    kind: str
    payload: dict[str, Any]
    attempt: int
    max_attempts: int
    user_id: str | None
    message_id: str | None


class JobContext:
    """Handed to a handler. Collects follow-up events instead of enqueuing them directly,
    so the hand-off commits in the same transaction that marks this job done."""

    def __init__(self, job: ClaimedJob) -> None:
        self._job = job
        self._emitted: list[JobEvent] = []

    @property
    def job_id(self) -> str:
        return self._job.id

    @property
    def kind(self) -> str:
        return self._job.kind

    @property
    def attempt(self) -> int:
        return self._job.attempt

    @property
    def max_attempts(self) -> int:
        return self._job.max_attempts

    @property
    def is_last_attempt(self) -> bool:
        return self._job.attempt >= self._job.max_attempts

    @property
    def payload(self) -> dict[str, Any]:
        return self._job.payload

    @property
    def user_id(self) -> str | None:
        return self._job.user_id

    @property
    def message_id(self) -> str | None:
        return self._job.message_id

    @property
    def emitted(self) -> list[JobEvent]:
        return list(self._emitted)

    def get(self, key: str, default: Any = None) -> Any:
        return self._job.payload.get(key, default)

    def require(self, key: str) -> str:
        value = self._job.payload.get(key)
        if value in (None, ""):
            raise MissingPayload(f"{self._job.kind} is missing payload key {key!r}")
        return str(value)

    def emit(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        user_id: str | None = None,
        message_id: str | None = None,
        delay_seconds: float = 0.0,
        max_attempts: int | None = None,
        priority: int = 0,
    ) -> None:
        self._emitted.append(
            JobEvent(
                kind=kind,
                payload=dict(payload or {}),
                idempotency_key=idempotency_key,
                user_id=user_id if user_id is not None else self._job.user_id,
                message_id=message_id,
                delay_seconds=delay_seconds,
                max_attempts=max_attempts,
                priority=priority,
            )
        )
