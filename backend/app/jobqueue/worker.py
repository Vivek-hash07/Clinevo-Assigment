"""In-process worker pool.

A pool of daemon threads polls `queue_jobs`, runs the handler for each claimed job,
and commits the follow-up jobs together with the completion. A maintenance thread
reclaims jobs from dead workers and schedules the recurring mailbox poll.

Threads (not asyncio) because every pipeline step is blocking: pdfplumber, Tesseract,
psycopg, and the OpenRouter HTTP client all release the GIL while they wait.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.jobqueue import store
from app.jobqueue.handlers import KIND_MAIL_SYNC  # noqa: F401  (imports register the handlers)
from app.jobqueue.registry import get_handler
from app.jobqueue.types import JobContext, JobEvent, NonRetriableError

logger = logging.getLogger(__name__)

IDLE_SLEEP_MIN = 0.25
IDLE_SLEEP_MAX = 2.0

# Bugs in our own code, not transient infrastructure faults: a retry would fail
# identically, so burn the attempt budget only on errors that could actually clear.
BUG_ERRORS = (
    NameError,
    AttributeError,
    TypeError,
    ImportError,
    IndexError,
    KeyError,
    NotImplementedError,
    UnboundLocalError,
)


@dataclass
class WorkerStats:
    started_at: float
    processed: int = 0
    failed: int = 0


class QueueWorker:
    def __init__(
        self,
        *,
        concurrency: int,
        lease_seconds: int,
        poll_interval: float,
        sync_interval_seconds: int,
        purge_after_days: int,
    ) -> None:
        self.concurrency = max(1, concurrency)
        self.lease_seconds = max(30, lease_seconds)
        self.poll_interval = max(0.05, poll_interval)
        self.sync_interval_seconds = max(0, sync_interval_seconds)
        self.purge_after_days = purge_after_days
        self.instance_id = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._stats = WorkerStats(started_at=time.time())
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        for index in range(self.concurrency):
            thread = threading.Thread(
                target=self._run_loop,
                name=f"queue-worker-{index}",
                args=(f"{self.instance_id}:{index}",),
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        maintenance = threading.Thread(target=self._maintenance_loop, name="queue-maintenance", daemon=True)
        maintenance.start()
        self._threads.append(maintenance)
        logger.info(
            "queue worker started: %s threads, instance %s, mailbox poll every %ss",
            self.concurrency,
            self.instance_id,
            self.sync_interval_seconds or "off",
        )

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        deadline = time.time() + timeout
        for thread in self._threads:
            remaining = max(0.1, deadline - time.time())
            thread.join(timeout=remaining)
        self._threads.clear()
        logger.info("queue worker stopped")

    @property
    def running(self) -> bool:
        return any(thread.is_alive() for thread in self._threads)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "instance_id": self.instance_id,
                "concurrency": self.concurrency,
                "running": self.running,
                "uptime_seconds": int(time.time() - self._stats.started_at),
                "processed": self._stats.processed,
                "failed": self._stats.failed,
                "lease_seconds": self.lease_seconds,
                "mailbox_poll_seconds": self.sync_interval_seconds,
            }

    # -------------------------------------------------------------------- looping

    def _run_loop(self, worker_id: str) -> None:
        backoff = IDLE_SLEEP_MIN
        while not self._stop.is_set():
            try:
                job = store.claim_next(worker_id)
            except Exception:
                logger.exception("queue: claim failed")
                self._stop.wait(IDLE_SLEEP_MAX)
                continue

            if job is None:
                # Back off while idle so an empty queue does not hammer Postgres.
                self._stop.wait(backoff)
                backoff = min(backoff * 1.5, IDLE_SLEEP_MAX)
                continue

            backoff = IDLE_SLEEP_MIN
            self._execute(job)

    def _execute(self, job) -> None:
        spec = get_handler(job.kind)
        if spec is None:
            store.fail(job.id, f"No handler registered for kind {job.kind!r}", retriable=False)
            logger.error("queue: no handler for %s (job %s)", job.kind, job.id)
            return

        ctx = JobContext(job)
        started = time.perf_counter()
        try:
            result = spec.fn(ctx) or {}
        except NonRetriableError as exc:
            self._record_failure(job, str(exc) or type(exc).__name__, retriable=False)
            return
        except Exception as exc:
            is_bug = isinstance(exc, BUG_ERRORS)
            logger.exception("queue: %s raised on attempt %s (job %s)", job.kind, job.attempt, job.id)
            self._record_failure(job, f"{type(exc).__name__}: {exc}", retriable=not is_bug)
            return

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        try:
            store.complete(
                job.id,
                result=result,
                follow_ups=ctx.emitted,
                skipped=bool(result.get("skip")) if isinstance(result, dict) else False,
            )
        except Exception:
            logger.exception("queue: could not record completion of %s (%s)", job.kind, job.id)
            return

        with self._lock:
            self._stats.processed += 1
        logger.info(
            "queue: %s ok in %sms (attempt %s/%s, %s follow-ups)",
            job.kind,
            elapsed_ms,
            job.attempt,
            job.max_attempts,
            len(ctx.emitted),
        )

    def _record_failure(self, job, error: str, *, retriable: bool) -> None:
        try:
            outcome = store.fail(job.id, error, retriable=retriable)
        except Exception:
            logger.exception("queue: could not record failure of %s (%s)", job.kind, job.id)
            return
        with self._lock:
            if outcome == store.STATUS_FAILED:
                self._stats.failed += 1
        level = logging.ERROR if outcome == store.STATUS_FAILED else logging.WARNING
        logger.log(
            level,
            "queue: %s %s on attempt %s/%s — %s",
            job.kind,
            "failed" if outcome == store.STATUS_FAILED else "will retry",
            job.attempt,
            job.max_attempts,
            error[:400],
        )

    # ---------------------------------------------------------------- maintenance

    def _maintenance_loop(self) -> None:
        last_sync = 0.0
        last_purge = 0.0
        tick = 5.0
        while not self._stop.is_set():
            now = time.time()
            try:
                reclaimed = store.reclaim_stale(self.lease_seconds)
                if reclaimed:
                    logger.warning("queue: reclaimed %s job(s) from an expired lease", reclaimed)
            except Exception:
                logger.exception("queue: reclaim_stale failed")

            if self.sync_interval_seconds and now - last_sync >= self.sync_interval_seconds:
                last_sync = now
                try:
                    # The idempotency key collapses duplicates, so several API instances
                    # polling on the same schedule still produce one sync job.
                    store.enqueue(
                        JobEvent(
                            kind=KIND_MAIL_SYNC,
                            payload={"trigger": "schedule"},
                            idempotency_key="mail-sync-all",
                            max_attempts=2,
                        )
                    )
                except Exception:
                    logger.exception("queue: could not schedule mailbox poll")

            if self.purge_after_days and now - last_purge >= 3600:
                last_purge = now
                try:
                    store.purge_finished(self.purge_after_days)
                except Exception:
                    logger.exception("queue: purge_finished failed")

            self._stop.wait(tick)


_worker: QueueWorker | None = None
_worker_lock = threading.Lock()


def start_worker() -> QueueWorker | None:
    """Start the pool unless disabled (QUEUE_WORKER_ENABLED=false), e.g. for tests or
    when running the API and the workers as separate Render services."""
    global _worker
    settings = get_settings()
    if not settings.queue_worker_enabled:
        logger.info("queue worker disabled by QUEUE_WORKER_ENABLED=false")
        return None
    with _worker_lock:
        if _worker is not None and _worker.running:
            return _worker
        _worker = QueueWorker(
            concurrency=settings.queue_worker_concurrency,
            lease_seconds=settings.queue_lease_seconds,
            poll_interval=settings.queue_poll_interval_seconds,
            sync_interval_seconds=settings.mail_sync_interval_seconds,
            purge_after_days=settings.queue_purge_after_days,
        )
        _worker.start()
        return _worker


def stop_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is not None:
            _worker.stop()
            _worker = None


def current_worker() -> QueueWorker | None:
    return _worker
