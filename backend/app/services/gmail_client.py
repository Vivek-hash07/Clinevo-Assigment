from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import GmailCredential
from app.security import decrypt_secret, encrypt_secret
from app.services.audit import write_audit
from app.services.mail_errors import MailAuthError, MailCursorExpired, MailProviderError

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailAuthError(MailAuthError):
    """Refresh token is missing, revoked, or otherwise unusable."""


class GmailHistoryExpired(MailCursorExpired):
    """Gmail no longer has history for the stored cursor; do a bounded inbox list."""


class GmailApiError(MailProviderError):
    """Gmail returned an error that may be transient."""


def _decrypt_optional(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return decrypt_secret(value)
    except ValueError:
        return None


def refresh_access_token(db: Session, cred: GmailCredential, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    refresh_token = _decrypt_optional(cred.refresh_token_encrypted)
    if not refresh_token:
        cred.sync_enabled = False
        cred.last_error = "Gmail refresh token is missing. Reconnect the mailbox."
        write_audit(db, "gmail.auth_missing", cred.user_id, {"gmail_email": cred.gmail_email})
        db.flush()
        raise GmailAuthError(cred.last_error)

    with httpx.Client(timeout=20.0) as client:
        response = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )

    if response.status_code >= 400:
        payload = {}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        error = str(payload.get("error") or "")
        if response.status_code in {400, 401} or error in {"invalid_grant", "unauthorized_client"}:
            cred.sync_enabled = False
            cred.last_error = "Gmail access was revoked or expired. Reconnect the mailbox."
            write_audit(
                db,
                "gmail.auth_revoked",
                cred.user_id,
                {"gmail_email": cred.gmail_email, "google_error": error or response.text[:300]},
            )
            db.flush()
            raise GmailAuthError(cred.last_error)
        raise GmailApiError(response.status_code, f"Google token refresh failed ({response.status_code})")

    tokens = response.json()
    access_token = tokens.get("access_token")
    if not access_token:
        raise GmailApiError(502, "Google did not return an access token")

    cred.access_token_encrypted = encrypt_secret(access_token)
    expires_in = int(tokens.get("expires_in") or 3600)
    cred.token_expiry = datetime.now(UTC) + timedelta(seconds=max(expires_in - 60, 30))
    rotated = tokens.get("refresh_token")
    if rotated:
        cred.refresh_token_encrypted = encrypt_secret(rotated)
    cred.last_error = None
    db.flush()
    return access_token


def valid_access_token(db: Session, cred: GmailCredential) -> str:
    token = _decrypt_optional(cred.access_token_encrypted)
    expiry = cred.token_expiry
    if token and expiry is not None:
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        if expiry > datetime.now(UTC) + timedelta(seconds=30):
            return token
    return refresh_access_token(db, cred)


class GmailClient:
    def __init__(self, db: Session, cred: GmailCredential, settings: Settings | None = None) -> None:
        self.db = db
        self.cred = cred
        self.settings = settings or get_settings()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {valid_access_token(self.db, self.cred)}"}

    def _request(self, method: str, url: str, *, params: dict | None = None, retry_auth: bool = True) -> dict:
        with httpx.Client(timeout=30.0) as client:
            response = client.request(method, url, headers=self._headers(), params=params)
        if response.status_code == 401 and retry_auth:
            refresh_access_token(self.db, self.cred)
            return self._request(method, url, params=params, retry_auth=False)
        if response.status_code == 404 and "history" in url:
            raise GmailHistoryExpired("Gmail history cursor expired")
        if response.status_code >= 400:
            raise GmailApiError(response.status_code, f"Gmail API {response.status_code}: {response.text[:400]}")
        if not response.content:
            return {}
        return response.json()

    def profile(self) -> dict:
        return self._request("GET", f"{GMAIL_API}/profile")

    def list_inbox_ids(self) -> tuple[list[str], str]:
        profile = self.profile()
        history_id = str(profile.get("historyId") or "")
        ids: list[str] = []
        page_token: str | None = None
        limit = max(1, self.settings.mail_sync_max_messages)
        while len(ids) < limit:
            params: dict[str, str | int] = {
                "q": "in:inbox",
                "includeSpamTrash": "false",
                "maxResults": min(100, limit - len(ids)),
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._request("GET", f"{GMAIL_API}/messages", params=params)
            for item in payload.get("messages") or []:
                message_id = item.get("id")
                if message_id:
                    ids.append(message_id)
                if len(ids) >= limit:
                    break
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return ids, history_id

    def list_history_ids(self, start_history_id: str) -> tuple[list[str], str]:
        ids: list[str] = []
        page_token: str | None = None
        latest = start_history_id
        limit = max(1, self.settings.mail_sync_max_messages)
        while len(ids) < limit:
            params: dict[str, str | int] = {
                "startHistoryId": start_history_id,
                "historyTypes": "messageAdded",
                "maxResults": 100,
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                payload = self._request("GET", f"{GMAIL_API}/history", params=params)
            except GmailHistoryExpired:
                return self.list_inbox_ids()
            latest = str(payload.get("historyId") or latest)
            for record in payload.get("history") or []:
                for added in record.get("messagesAdded") or []:
                    message_id = (added.get("message") or {}).get("id")
                    if message_id:
                        ids.append(message_id)
                    if len(ids) >= limit:
                        break
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        unique: list[str] = []
        seen: set[str] = set()
        for message_id in ids:
            if message_id not in seen:
                seen.add(message_id)
                unique.append(message_id)
        return unique, latest

    def get_message(self, gmail_message_id: str) -> dict:
        return self._request("GET", f"{GMAIL_API}/messages/{gmail_message_id}", params={"format": "full"})

    def get_attachment_bytes(self, gmail_message_id: str, attachment_id: str) -> bytes:
        payload = self._request(
            "GET",
            f"{GMAIL_API}/messages/{gmail_message_id}/attachments/{attachment_id}",
        )
        from app.services.gmail_parse import decode_gmail_data

        return decode_gmail_data(payload.get("data"))
