"""Errors shared by every mail provider, so callers do not branch on provider type."""

from __future__ import annotations


class MailAuthError(Exception):
    """Credentials are missing, revoked, or rejected. Retrying will not help; the user
    has to reconnect the mailbox."""


class MailCursorExpired(Exception):
    """The stored sync cursor is no longer valid (Gmail history expiry, or IMAP
    UIDVALIDITY changed). Fall back to a bounded listing."""


class MailProviderError(Exception):
    """The provider failed in a way that may be transient."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
