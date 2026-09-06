from __future__ import annotations

import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.schema_sync import ensure_schema
from app.routers import auth, gmail, health, messages, uploads

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
    yield


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
        if request.url.path.rstrip("/") == "/api/inngest":
            return await call_next(request)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and not _origin_allowed(
                origin, settings.frontend_url, settings.backend_url
            ):
                return JSONResponse(status_code=403, content={"detail": "Untrusted request origin"})
        return await call_next(request)

    application.include_router(health.router)
    application.include_router(auth.router)
    application.include_router(gmail.router)
    application.include_router(messages.router)
    application.include_router(uploads.router)

    import inngest.fast_api

    from app.inngest_client import inngest_client
    from app.jobs import INNGEST_FUNCTIONS

    inngest.fast_api.serve(application, inngest_client, INNGEST_FUNCTIONS)

    return application


app = create_app()
