from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import User
from app.security import decode_token

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def _user_from_access_cookie(request: Request, db: Session, settings: Settings) -> User | None:
    token = request.cookies.get(settings.access_cookie_name)
    if not token:
        return None
    try:
        payload = decode_token(token, "access", settings)
        user_id = payload["sub"]
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    return db.get(User, user_id)


def get_current_user(
    request: Request,
    db: DbSession,
    settings: AppSettings,
) -> User:
    user = _user_from_access_cookie(request, db, settings)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    return user


def get_optional_user(
    request: Request,
    db: DbSession,
    settings: AppSettings,
) -> User | None:
    return _user_from_access_cookie(request, db, settings)


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def require_google_oauth(settings: AppSettings) -> Settings:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is unavailable right now. Please use email, or try again later.",
        )
    return settings


RequireGoogle = Annotated[Settings, Depends(require_google_oauth)]
