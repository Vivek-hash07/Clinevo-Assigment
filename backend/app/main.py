from __future__ import annotations

import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.jobqueue.worker import start_worker, stop_worker
from app.schema_sync import ensure_schema
from app.routers import auth, health, jobs, mail, messages, uploads

_VERCEL_ORIGIN = re.compile(r"^https://([a-z0-9-]+\.)*vercel\.app$", re.IGNORECASE)


def _cors_origins(frontend_url: str) -> list[str]:
    origins = {
        frontend_url.rstrip("/"),
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    }
    return sorted(origins)


def _trusted_origins(frontend_url: str, backend_url: str) -> set[str]:
    return {
        frontend_url.rstrip("/"),
        backend_url.rstrip("/"),
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    }


def _origin_allowed(origin: str, frontend_url: str, backend_url: str) -> bool:
    normalized = origin.rstrip("/")
    return normalized in _trusted_origins(frontend_url, backend_url) or bool(
        _VERCEL_ORIGIN.fullmatch(normalized)
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    start_worker()
    try:
        yield
    finally:
        stop_worker()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Clinevo Smart Inbox API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(settings.frontend_url),
        allow_origin_regex=r"https://.*\.vercel\.app",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def reject_untrusted_browser_writes(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and not _origin_allowed(
                origin, settings.frontend_url, settings.backend_url
            ):
                return JSONResponse(status_code=403, content={"detail": "Untrusted request origin"})
        return await call_next(request)

    @application.exception_handler(OperationalError)
    async def database_unavailable(_request: Request, _exc: OperationalError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "The database is temporarily unreachable (Neon). "
                    "Wait a few seconds and try again. If this persists, wake the Neon project "
                    "or check your network / VPN."
                )
            },
        )

    application.include_router(health.router)
    application.include_router(auth.router)
    application.include_router(mail.router)
    application.include_router(mail.gmail_compat)
    application.include_router(jobs.router)
    application.include_router(messages.router)
    application.include_router(uploads.router)

    return application


app = create_app()
