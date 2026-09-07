"""Postgres-backed in-process job queue.

Replaces the earlier Inngest dependency: the assignment asks for "a simple queue
(even an in-process one)", and keeping the queue inside the API removes an external
service that the app cannot start without.
"""

from app.jobqueue.store import enqueue, enqueue_in_session
from app.jobqueue.types import JobContext, JobEvent, NonRetriableError

__all__ = [
    "JobContext",
    "JobEvent",
    "NonRetriableError",
    "enqueue",
    "enqueue_in_session",
]
