"""Maps a job kind to the function that runs it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.jobqueue.types import DEFAULT_MAX_ATTEMPTS, JobContext

Handler = Callable[[JobContext], dict[str, Any] | None]


@dataclass(frozen=True)
class HandlerSpec:
    kind: str
    fn: Handler
    max_attempts: int
    label: str


_REGISTRY: dict[str, HandlerSpec] = {}


def register(
    kind: str,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    label: str | None = None,
) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        if kind in _REGISTRY:
            raise RuntimeError(f"Duplicate queue handler for {kind!r}")
        _REGISTRY[kind] = HandlerSpec(
            kind=kind,
            fn=fn,
            max_attempts=max_attempts,
            label=label or kind,
        )
        return fn

    return decorator


def get_handler(kind: str) -> HandlerSpec | None:
    return _REGISTRY.get(kind)


def default_max_attempts(kind: str) -> int:
    spec = _REGISTRY.get(kind)
    return spec.max_attempts if spec else DEFAULT_MAX_ATTEMPTS


def registered_kinds() -> list[str]:
    return sorted(_REGISTRY)


def all_specs() -> list[HandlerSpec]:
    return [_REGISTRY[kind] for kind in sorted(_REGISTRY)]
