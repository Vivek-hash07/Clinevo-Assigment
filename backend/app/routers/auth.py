from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.deps import AppSettings, CurrentUser, DbSession, OptionalUser

from app.schemas import (
    AuthConfigOut,
    ForgotPasswordRequest,
    LoginRequest,
    MessageOut,
    RegisterRequest,
    ResetPasswordRequest,
    UserOut,
)
from app.security import new_oauth_state
from app.services.auth import (
    authenticate_user,
    clear_auth_cookies,
    google_authorize_url,
    register_user,
    request_password_reset,
    reset_password,
    revoke_refresh_token,
    rotate_refresh_token,
    set_auth_cookies,
    upsert_google_user,
    user_to_out,
    write_audit,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
GOOGLE_INTENTS = {"signin", "signup", "gmail"}
GOOGLE_NEXT_PATHS = {"/inbox"}


def _frontend_redirect(path: str, **query: str) -> str:
    settings = get_settings()
    base = settings.frontend_url.rstrip("/")
    qs = urlencode({k: v for k, v in query.items() if v})
    return f"{base}{path}" + (f"?{qs}" if qs else "")


@router.get("/config", response_model=AuthConfigOut)
def auth_config() -> AuthConfigOut:
    settings = get_settings()
    return AuthConfigOut(
        google_enabled=bool(settings.google_client_id and settings.google_client_secret),
        google_redirect_uri=settings.google_redirect_uri,
        frontend_url=settings.frontend_url,
        gmail_scope=settings.gmail_scope,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, response: Response, db: DbSession) -> UserOut:
    user = register_user(db, payload.name, payload.email, payload.password)
    set_auth_cookies(response, db, user.id)
    return user_to_out(user)


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, response: Response, db: DbSession) -> UserOut:
    user = authenticate_user(db, payload.email, payload.password)
    set_auth_cookies(response, db, user.id)
    return user_to_out(user)


@router.post("/forgot-password", response_model=MessageOut)
def forgot_password(payload: ForgotPasswordRequest, db: DbSession) -> MessageOut:
    request_password_reset(db, payload.email)
    return MessageOut(
        ok=True,
        message="If an account exists for that email, we sent a reset link.",
    )


@router.post("/reset-password", response_model=UserOut)
def reset_password_route(payload: ResetPasswordRequest, response: Response, db: DbSession) -> UserOut:
    user = reset_password(db, payload.token, payload.password)
    set_auth_cookies(response, db, user.id)
    return user_to_out(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: DbSession, user: OptionalUser) -> dict[str, bool]:
    settings = get_settings()
    revoke_refresh_token(db, request.cookies.get(settings.refresh_cookie_name))
    if user is not None:
        write_audit(db, "auth.logout", user.id, {})
        db.commit()
    clear_auth_cookies(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return user_to_out(user)


@router.post("/refresh", response_model=UserOut)
def refresh(request: Request, response: Response, db: DbSession) -> UserOut:
    settings = get_settings()
    token = request.cookies.get(settings.refresh_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh session")
    try:
        user = rotate_refresh_token(db, token, settings)
    except HTTPException as exc:
        clear_auth_cookies(response)
        raise exc
    set_auth_cookies(response, db, user.id, settings)
    return user_to_out(user)


@router.get("/google")
def google_start(request: Request, settings: AppSettings) -> RedirectResponse:
    if not settings.google_client_id or not settings.google_client_secret:
        return RedirectResponse(_frontend_redirect("/sign-in", error="google_unavailable"), status_code=302)
    state = new_oauth_state()
    intent = request.query_params.get("intent", "signin")
    next_path = request.query_params.get("next", "/inbox")
    if intent not in GOOGLE_INTENTS:
        intent = "signin"
    if next_path not in GOOGLE_NEXT_PATHS:
        next_path = "/inbox"
    signed_state = f"{state}:{intent}:{next_path}"
    url = google_authorize_url(state, settings, gmail=intent == "gmail")
    # Store full signed_state in cookie; Google only echoes `state`.
    redirect = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        key=settings.oauth_state_cookie_name,
        value=signed_state,
        max_age=600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    return redirect


@router.get("/google/callback")
def google_callback(request: Request, db: DbSession, settings: AppSettings) -> RedirectResponse:
    if not settings.google_client_id or not settings.google_client_secret:
        return RedirectResponse(_frontend_redirect("/sign-in", error="google_unavailable"), status_code=302)
    error = request.query_params.get("error")
    if error:
        return RedirectResponse(_frontend_redirect("/sign-in", error="google_denied"), status_code=302)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    stored = request.cookies.get(settings.oauth_state_cookie_name, "")
    stored_state = stored.split(":", 1)[0] if stored else ""
    intent = "signin"
    next_path = "/inbox"
    if stored.count(":") >= 2:
        _, intent, next_path = stored.split(":", 2)
    if intent not in GOOGLE_INTENTS or next_path not in GOOGLE_NEXT_PATHS:
        intent = "signin"
        next_path = "/inbox"

    if not code or not state or not stored_state or state != stored_state:
        return RedirectResponse(_frontend_redirect("/sign-in", error="oauth_state"), status_code=302)

    try:
        user = upsert_google_user(db, settings, code)
    except HTTPException:
        return RedirectResponse(_frontend_redirect("/sign-in", error="oauth_failed"), status_code=302)
    except Exception:
        return RedirectResponse(_frontend_redirect("/sign-in", error="oauth_failed"), status_code=302)

    dest = _frontend_redirect(next_path)
    response = RedirectResponse(dest, status_code=status.HTTP_302_FOUND)
    set_auth_cookies(response, db, user.id, settings)
    response.delete_cookie(
        settings.oauth_state_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )
    return response
