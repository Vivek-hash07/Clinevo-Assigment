"""IMAP mailbox reader.

The alternative to Google OAuth for mail intake. Gmail's `gmail.readonly` scope is
"restricted", which keeps an unverified OAuth app limited to manually-added test
users; IMAP with an app password needs no Google review, so a reviewer can connect
any mailbox (Gmail, Outlook, Fastmail, a corporate server) with one form.

Sync uses UID as the cursor. UIDs only mean anything within one UIDVALIDITY
generation, so we store both and reset the cursor if the server changes it.
"""

from __future__ import annotations

import imaplib
import logging
import re
import socket
from dataclasses import dataclass

from app.services.mail_errors import MailAuthError, MailProviderError

logger = logging.getLogger(__name__)

# Gmail rejects app passwords that still contain the spaces shown in the UI.
_SPACES = re.compile(r"\s+")

DEFAULT_HOST = "imap.gmail.com"
DEFAULT_PORT = 993
DEFAULT_FOLDER = "INBOX"
CONNECT_TIMEOUT_SECONDS = 30

KNOWN_HOSTS = {
    "gmail.com": "imap.gmail.com",
    "googlemail.com": "imap.gmail.com",
    "outlook.com": "outlook.office365.com",
    "hotmail.com": "outlook.office365.com",
    "live.com": "outlook.office365.com",
    "office365.com": "outlook.office365.com",
    "yahoo.com": "imap.mail.yahoo.com",
    "fastmail.com": "imap.fastmail.com",
    "icloud.com": "imap.mail.me.com",
    "zoho.com": "imap.zoho.com",
    "yandex.com": "imap.yandex.com",
}


def normalize_app_password(value: str) -> str:
    return _SPACES.sub("", value or "")


def suggest_host(email: str) -> str:
    domain = (email or "").rsplit("@", 1)[-1].strip().lower()
    return KNOWN_HOSTS.get(domain, f"imap.{domain}" if domain else DEFAULT_HOST)


@dataclass
class ImapSettings:
    email: str
    password: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    use_ssl: bool = True
    folder: str = DEFAULT_FOLDER


@dataclass
class FolderState:
    uid_validity: str
    exists: int


def _friendly_login_error(detail: str, host: str) -> str:
    lowered = detail.lower()
    if "imap" in lowered and ("disabled" in lowered or "not enabled" in lowered):
        return (
            "The mail server refused IMAP access. Enable IMAP in the mailbox settings "
            "(Gmail: Settings → Forwarding and POP/IMAP → Enable IMAP)."
        )
    if "application-specific password" in lowered or "app password" in lowered:
        return (
            "Google requires an App Password for IMAP. Enable 2-Step Verification, then "
            "create one at myaccount.google.com/apppasswords and paste the 16 characters."
        )
    if "authenticationfailed" in lowered.replace(" ", "") or "invalid credentials" in lowered:
        return f"{host} rejected the address or app password. Check both and try again."
    return f"{host} rejected the login: {detail}"


class ImapMailbox:
    """A short-lived IMAP connection. Open it with `with`, one sync per connection."""

    def __init__(self, settings: ImapSettings) -> None:
        self.settings = settings
        self._conn: imaplib.IMAP4 | None = None

    # ------------------------------------------------------------------ lifecycle

    def __enter__(self) -> ImapMailbox:
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def connect(self) -> None:
        cfg = self.settings
        try:
            if cfg.use_ssl:
                self._conn = imaplib.IMAP4_SSL(cfg.host, cfg.port, timeout=CONNECT_TIMEOUT_SECONDS)
            else:
                self._conn = imaplib.IMAP4(cfg.host, cfg.port, timeout=CONNECT_TIMEOUT_SECONDS)
        except (socket.gaierror, socket.herror) as exc:
            raise MailProviderError(502, f"Could not resolve IMAP host {cfg.host}: {exc}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise MailProviderError(504, f"Timed out connecting to {cfg.host}:{cfg.port}") from exc
        except OSError as exc:
            raise MailProviderError(502, f"Could not reach {cfg.host}:{cfg.port}: {exc}") from exc

        try:
            self._conn.login(cfg.email, cfg.password)
        except imaplib.IMAP4.error as exc:
            detail = _decode_imap_error(exc)
            self.close()
            raise MailAuthError(_friendly_login_error(detail, cfg.host)) from exc

    def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            if conn.state == "SELECTED":
                conn.close()
        except Exception:
            pass
        try:
            conn.logout()
        except Exception:
            pass

    @property
    def _client(self) -> imaplib.IMAP4:
        if self._conn is None:
            raise MailProviderError(500, "IMAP connection is not open")
        return self._conn

    # --------------------------------------------------------------------- reading

    def select_folder(self, readonly: bool = True) -> FolderState:
        folder = self.settings.folder or DEFAULT_FOLDER
        # Quote the mailbox name so folders containing spaces work.
        status, data = self._client.select(f'"{folder}"', readonly=readonly)
        if status != "OK":
            raise MailProviderError(404, f"Cannot open IMAP folder {folder!r}: {_first(data)}")
        exists = int(_first(data) or 0)
        status, uidv = self._client.response("UIDVALIDITY")
        uid_validity = (_first(uidv) or "").strip()
        if not uid_validity:
            status, fetched = self._client.status(f'"{folder}"', "(UIDVALIDITY)")
            match = re.search(r"UIDVALIDITY\s+(\d+)", _first(fetched) or "")
            uid_validity = match.group(1) if match else "0"
        return FolderState(uid_validity=str(uid_validity), exists=exists)

    def list_uids_since(self, last_uid: int | None, limit: int) -> list[int]:
        """UIDs strictly greater than `last_uid`, oldest first, capped at `limit`."""
        start = (last_uid or 0) + 1
        status, data = self._client.uid("SEARCH", None, f"UID {start}:*")
        if status != "OK":
            raise MailProviderError(502, f"IMAP UID SEARCH failed: {_first(data)}")
        raw = (_first(data) or "").split()
        uids = sorted({int(item) for item in raw if item.isdigit()})
        # "UID n:*" always returns at least the highest UID, even when it is < n.
        uids = [uid for uid in uids if uid >= start]
        if limit > 0 and len(uids) > limit:
            uids = uids[-limit:]
        return uids

    def list_recent_uids(self, limit: int) -> list[int]:
        status, data = self._client.uid("SEARCH", None, "ALL")
        if status != "OK":
            raise MailProviderError(502, f"IMAP UID SEARCH failed: {_first(data)}")
        raw = (_first(data) or "").split()
        uids = sorted({int(item) for item in raw if item.isdigit()})
        if limit > 0 and len(uids) > limit:
            uids = uids[-limit:]
        return uids

    def fetch_rfc822(self, uid: int) -> bytes:
        status, data = self._client.uid("FETCH", str(uid), "(BODY.PEEK[])")
        if status != "OK":
            raise MailProviderError(502, f"IMAP FETCH failed for UID {uid}: {_first(data)}")
        for item in data or []:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
                return bytes(item[1])
        raise MailProviderError(404, f"IMAP returned no body for UID {uid}")


def _first(data: object) -> str:
    if isinstance(data, (list, tuple)):
        for item in data:
            if isinstance(item, (bytes, bytearray)):
                return item.decode("utf-8", errors="replace")
            if isinstance(item, str):
                return item
        return ""
    if isinstance(data, (bytes, bytearray)):
        return data.decode("utf-8", errors="replace")
    return str(data or "")


def _decode_imap_error(exc: Exception) -> str:
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], (bytes, bytearray)):
        return args[0].decode("utf-8", errors="replace")
    return str(exc)


def verify_credentials(settings: ImapSettings) -> dict[str, object]:
    """Log in, open the folder, and log out. Used by the "Test connection" button so a
    reviewer gets a clear error before we store anything."""
    with ImapMailbox(settings) as box:
        state = box.select_folder(readonly=True)
        return {
            "ok": True,
            "host": settings.host,
            "port": settings.port,
            "folder": settings.folder,
            "message_count": state.exists,
            "uid_validity": state.uid_validity,
        }
