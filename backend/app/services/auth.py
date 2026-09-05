from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlencode

import httpx
from fastapi import HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import GmailCredential, PasswordResetToken, RefreshToken, User
from app.schemas import UserOut
from app.security import (
    create_token,
    encrypt_secret,
    hash_password,
    hash_token,
    new_opaque_token,
    verify_password,
)
from app.services.audit import write_audit

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
logger = logging.getLogger(__name__)


def _cookie_samesite(settings: Settings) -> str:
    return settings.cookie_samesite


def set_auth_cookies(
    response: Response,
    db: Session,
    user_id: str,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    secure = settings.cookie_secure
    samesite = _cookie_samesite(settings)
    refresh_token = new_opaque_token()
    db.add(
        RefreshToken(
            user_id=str(user_id),
            token_hash=hash_token(refresh_token),
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_seconds),
        )
    )
    db.commit()
    response.set_cookie(
        key=settings.access_cookie_name,
        value=create_token(user_id, "access", settings),
        max_age=settings.access_token_ttl_seconds,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/api/auth",
    )


def clear_auth_cookies(response: Response, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    attributes = {
        "secure": settings.cookie_secure,
        "httponly": True,
        "samesite": settings.cookie_samesite,
    }
    response.delete_cookie(settings.access_cookie_name, path="/", **attributes)
    response.delete_cookie(settings.refresh_cookie_name, path="/api/auth", **attributes)
    response.delete_cookie(settings.oauth_state_cookie_name, path="/", **attributes)


def rotate_refresh_token(db: Session, token: str, settings: Settings | None = None) -> User:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    stored = db.scalar(
        select(RefreshToken)
        .where(
            RefreshToken.token_hash == hash_token(token),
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .with_for_update()
    )
    if stored is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    stored.revoked_at = now
    user = db.get(User, stored.user_id)
    if user is None:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    db.commit()
    return user


def revoke_refresh_token(db: Session, token: str | None) -> None:
    if not token:
        return
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(token), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()


def user_to_out(user: User) -> UserOut:
    cred = user.gmail_credential
    google_linked = bool(user.google_sub)
    gmail_connected = bool(cred and cred.refresh_token_encrypted and cred.sync_enabled)
    if google_linked and not user.password_hash:
        provider = "google"
    elif user.password_hash and google_linked:
        provider = "google+password"
    elif user.password_hash:
        provider = "password"
    else:
        provider = "google"
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        google_linked=google_linked,
        gmail_connected=gmail_connected,
        auth_provider=provider,
    )


def register_user(db: Session, name: str, email: str, password: str) -> User:
    email_norm = email.strip().lower()
    existing = db.scalar(select(User).where(User.email == email_norm))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")
    user = User(
        email=email_norm,
        name=name.strip(),
        password_hash=hash_password(password),
    )
    db.add(user)
    try:
        db.flush()
        write_audit(db, "auth.register", user.id, {"method": "password", "email": email_norm})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from exc
    db.refresh(user)
    return user


def request_password_reset(db: Session, email: str) -> None:
    from app.services.mail import send_password_reset

    settings = get_settings()
    email_norm = email.strip().lower()
    user = db.scalar(select(User).where(User.email == email_norm))
    if user is None:
        return
    now = datetime.now(UTC)
    token = new_opaque_token()
    token_digest = hash_token(token)
    db.add(
        PasswordResetToken(
            user_id=str(user.id),
            token_hash=token_digest,
            expires_at=now + timedelta(seconds=settings.reset_token_ttl_seconds),
        )
    )
    write_audit(db, "auth.forgot_password", user.id, {"email": email_norm})
    db.commit()
    reset_url = f"{settings.frontend_url.rstrip('/')}/reset-password?token={quote(token, safe='')}"
    try:
        send_password_reset(user.email, user.name, reset_url, settings)
    except Exception as exc:
        logger.exception("Password reset email delivery failed")
        db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_digest)
            .values(used_at=datetime.now(UTC))
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="We could not send the email. Please try again in a moment.",
        ) from exc
    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == str(user.id),
            PasswordResetToken.token_hash != token_digest,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=datetime.now(UTC))
    )
    db.commit()


def reset_password(db: Session, token: str, password: str) -> User:
    now = datetime.now(UTC)
    stored = db.scalar(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == hash_token(token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .with_for_update()
    )
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired.",
        )
    user = db.get(User, stored.user_id)
    if user is None:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This reset link is invalid.")
    stored.used_at = now
    user.password_hash = hash_password(password)
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == str(user.id), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    write_audit(db, "auth.reset_password", user.id, {})
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    email_norm = email.strip().lower()
    user = db.scalar(select(User).where(User.email == email_norm))
    if user is None or not user.password_hash or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    write_audit(db, "auth.login", user.id, {"method": "password"})
    db.commit()
    return user


def google_authorize_url(state: str, settings: Settings, *, gmail: bool = False) -> str:
    scopes = settings.google_scopes
    if gmail:
        scopes = f"{settings.google_scopes} {settings.gmail_scope}".strip()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "include_granted_scopes": "true",
        "state": state,
    }
    if gmail:
        params["access_type"] = "offline"
        params["prompt"] = "consent"
    else:
        params["prompt"] = "select_account"
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def _exchange_code(code: str, settings: Settings) -> dict:
    data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }
    with httpx.Client(timeout=20.0) as client:
        token_res = client.post(GOOGLE_TOKEN_URL, data=data)
        if token_res.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google did not accept the authorization code. Check the redirect URI.",
            )
        tokens = token_res.json()
        access_token = tokens.get("access_token")
        if not access_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google did not return an access token")
        info_res = client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if info_res.status_code >= 400:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not load the Google profile")
        profile = info_res.json()
    return {"tokens": tokens, "profile": profile}


def upsert_google_user(db: Session, settings: Settings, code: str) -> User:
    bundle = _exchange_code(code, settings)
    tokens = bundle["tokens"]
    profile = bundle["profile"]

    sub = profile.get("sub")
    email = (profile.get("email") or "").strip().lower()
    email_verified = profile.get("email_verified") is True
    name = (profile.get("name") or profile.get("given_name") or email.split("@")[0]).strip()
    picture = profile.get("picture")
    if not sub or not email or not email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google did not provide a verified email address",
        )

    user = db.scalar(select(User).where(User.google_sub == sub))
    created = False
    if user is None:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, name=name, google_sub=sub, avatar_url=picture)
            db.add(user)
            db.flush()
            created = True
        else:
            user.google_sub = sub
            if picture:
                user.avatar_url = picture
            if not user.name:
                user.name = name
    else:
        user.email = email
        if name:
            user.name = name
        if picture:
            user.avatar_url = picture

    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")
    expires_in = tokens.get("expires_in")
    scope = tokens.get("scope") or settings.google_scopes
    gmail_granted = GMAIL_SCOPE in scope
    expiry = None
    if expires_in:
        from datetime import timedelta

        expiry = datetime.now(UTC) + timedelta(seconds=int(expires_in))

    if gmail_granted:
        cred = user.gmail_credential
        if cred is None:
            cred = GmailCredential(user_id=user.id)
            db.add(cred)
            db.flush()
            user.gmail_credential = cred

        cred.gmail_email = email
        cred.scopes = scope
        cred.token_expiry = expiry
        cred.last_error = None
        if access_token:
            cred.access_token_encrypted = encrypt_secret(access_token)
        if refresh_token:
            cred.refresh_token_encrypted = encrypt_secret(refresh_token)
        cred.sync_enabled = bool(cred.refresh_token_encrypted)
        if refresh_token:
            write_audit(
                db,
                "gmail.connected",
                user.id,
                {"gmail_email": email, "has_refresh_token": True},
            )
        elif not cred.refresh_token_encrypted:
            cred.last_error = "Google did not return a refresh token. Reconnect mail with consent."

    write_audit(
        db,
        "auth.register" if created else "auth.login",
        user.id,
        {
            "method": "google",
            "gmail_scope": GMAIL_SCOPE in scope,
            "refresh_token": bool(tokens.get("refresh_token")),
        },
    )
    db.commit()
    db.refresh(user)
    return user
