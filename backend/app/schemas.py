from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


def _validate_password(value: str) -> str:
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return value


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    _password_bytes = field_validator("password")(_validate_password)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=2048)
    password: str = Field(min_length=8, max_length=128)

    _password_bytes = field_validator("password")(_validate_password)


class UserOut(BaseModel):
    id: UUID
    email: str
    name: str
    avatar_url: str | None
    google_linked: bool
    gmail_connected: bool
    auth_provider: str

    model_config = {"from_attributes": True}


class AuthConfigOut(BaseModel):
    google_enabled: bool
    google_redirect_uri: str
    frontend_url: str
    gmail_scope: str


class HealthOut(BaseModel):
    status: str
    service: str
    db: str


class MessageOut(BaseModel):
    ok: bool
    message: str


class SyncMailOut(BaseModel):
    ok: bool
    queued: bool
    gmail_connected: bool
    message: str
    queued_event_ids: list[str] = []


class GmailStatusOut(BaseModel):
    connected: bool
    sync_enabled: bool
    gmail_email: str | None
    last_synced_at: str | None
    last_error: str | None


class SeedSyntheticOut(BaseModel):
    ok: bool
    to: str
    count: int
    sent: list[str]
    message: str


class QueueCounts(BaseModel):
    pending: int = 0
    processing: int = 0
    ready: int = 0
    reviewed: int = 0
    total: int = 0


class QueueAttachmentOut(BaseModel):
    id: str
    filename: str
    mime: str
    skipped: bool
    skip_reason: str | None
    size_bytes: int | None
    processed: bool


class QueueItemOut(BaseModel):
    id: str
    sender: str
    subject: str
    status: str
    sent_at: str | None
    snippet: str = ""
    pdf_count: int = 0
    skipped_attachment_count: int = 0


class QueueListOut(BaseModel):
    items: list[QueueItemOut]
    counts: QueueCounts
    status: str | None = None
    limit: int
    offset: int


class QueueDetailOut(QueueItemOut):
    body: str
    body_html: str | None = None
    gmail_message_id: str | None = None
    attachments: list[QueueAttachmentOut]
