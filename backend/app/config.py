from functools import lru_cache
from pathlib import Path
from typing import Literal

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
        if self.app_env != "production":
            return self
        if not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must be true in production")
        if not self.frontend_url.startswith("https://") or not self.backend_url.startswith("https://"):
            raise ValueError("FRONTEND_URL and BACKEND_URL must use HTTPS in production")
        if len(self.jwt_secret) < 32 or len(self.token_encryption_key) < 32:
            raise ValueError("JWT_SECRET and TOKEN_ENCRYPTION_KEY must each be at least 32 characters")
        if not all((self.smtp_host, self.smtp_user, self.smtp_password, self.smtp_from)):
            raise ValueError("SMTP settings are required in production")
        if self.inngest_dev:
            raise ValueError("INNGEST_DEV must be false in production")
        if not self.inngest_signing_key:
            raise ValueError("INNGEST_SIGNING_KEY is required in production")
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is required in production")
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
