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
