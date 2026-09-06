import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    database_url: str
    jwt_secret: str
    token_encryption_key: str

    frontend_url: str = "http://localhost:8000"
    backend_url: str = "http://localhost:8080"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    aws_region: str = "ap-south-1"

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8080/api/auth/google/callback"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    @field_validator("smtp_password", mode="before")
    @classmethod
    def _strip_smtp_password(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().strip('"').strip("'")
        return value

    @model_validator(mode="after")
    def _validate_production(self) -> "Settings":
        render_url = (os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
        updates: dict[str, object] = {}
        if render_url.startswith("https://") and self.backend_url.startswith("http://localhost"):
            updates["backend_url"] = render_url
        backend_url = str(updates.get("backend_url", self.backend_url)).rstrip("/")
        if (
            render_url.startswith("https://")
            and self.google_redirect_uri.startswith("http://localhost")
        ):
            updates["google_redirect_uri"] = f"{backend_url}/api/auth/google/callback"
        if updates:
            self = self.model_copy(update=updates)

        if self.app_env != "production":
            return self

        # Render sets RENDER_EXTERNAL_URL; allow boot before FRONTEND_URL is configured.
        if not self.frontend_url.startswith("https://") and self.backend_url.startswith("https://"):
            self = self.model_copy(update={"frontend_url": self.backend_url})

        errors: list[str] = []
        if not self.cookie_secure:
            errors.append("COOKIE_SECURE must be true")
        if not self.backend_url.startswith("https://"):
            errors.append("BACKEND_URL must be an https:// URL (your Render service)")
        if len(self.jwt_secret) < 32 or len(self.token_encryption_key) < 32:
            errors.append("JWT_SECRET and TOKEN_ENCRYPTION_KEY must each be at least 32 characters")
        if not all((self.smtp_host, self.smtp_user, self.smtp_password, self.smtp_from)):
            errors.append("SMTP_HOST, SMTP_USER, SMTP_PASSWORD, and SMTP_FROM are required")
        if self.inngest_dev:
            errors.append("INNGEST_DEV must be false")
        if not self.inngest_signing_key:
            errors.append("INNGEST_SIGNING_KEY is required")
        if not self.openrouter_api_key:
            errors.append("OPENROUTER_API_KEY is required")
        if errors:
            raise ValueError("Set these in the Render Environment tab: " + "; ".join(errors))

        frontend_host = (urlparse(self.frontend_url).hostname or "").lower()
        backend_host = (urlparse(self.backend_url).hostname or "").lower()
        if frontend_host and backend_host and frontend_host != backend_host:
            # Vercel UI + Render API are different sites; Lax cookies would not be sent.
            return self.model_copy(update={"cookie_samesite": "none", "cookie_secure": True})
        return self

    access_token_ttl_seconds: int = 60 * 15
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 7
    reset_token_ttl_seconds: int = 60 * 30

    access_cookie_name: str = "sia_access"
    refresh_cookie_name: str = "sia_refresh"
    oauth_state_cookie_name: str = "sia_oauth_state"

    google_scopes: str = Field(default="openid email profile")
    gmail_scope: str = Field(default="https://www.googleapis.com/auth/gmail.readonly")

    inngest_app_id: str = "clinevo-smart-inbox"
    inngest_dev: bool = True
    inngest_event_key: str = ""
    inngest_signing_key: str = ""
    gmail_sync_max_messages: int = 50
    attachment_max_bytes: int = 20 * 1024 * 1024
    attachment_dir: str = str(BACKEND_DIR / "var" / "attachments")
    message_body_max_chars: int = 500_000

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_vision_model: str = "openai/gpt-4o-mini"
    openrouter_timeout_seconds: int = 90
    openrouter_max_retries: int = 3
    openrouter_http_referer: str = ""
    openrouter_app_title: str = "Clinevo Smart Inbox"

    pdf_max_pages: int = 40
    pdf_render_scale: float = 2.0
    pdf_page_text_max_chars: int = 20_000
    ocr_confidence_threshold: float = 0.72
    llm_hallucination_overlap_min: float = 0.18

    ai_pack_max_chars: int = 60_000
    ai_email_max_chars: int = 20_000
    ai_page_max_chars: int = 8_000
    ai_classify_min_confidence: float = 0.35
    ai_quote_min_chars: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
