from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser

from app.constants import PDF_MIME_TYPES

_BODY_WHITESPACE = re.compile(r"[ \t]+\n")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


class _HTMLTextExtractor(HTMLParser):
    _SKIP = frozenset({"script", "style", "head"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in {"p", "div", "br", "tr", "li", "h1", "h2", "h3"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    def text(self) -> str:
        joined = " ".join(self._chunks)
        joined = _BODY_WHITESPACE.sub("\n", joined)
        return _MULTI_NEWLINE.sub("\n\n", joined).strip()


def html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(unescape(html))
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html).strip()
    return parser.text()


def decode_gmail_data(data: str | None) -> bytes:
    if not data:
        return b""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def header_map(payload: dict) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in payload.get("headers") or []:
        name = (item.get("name") or "").strip().lower()
        if name:
            values[name] = item.get("value") or ""
    return values


def normalize_mime(mime: str | None) -> str:
    return (mime or "application/octet-stream").split(";", 1)[0].strip().lower()


def is_pdf(filename: str, mime: str) -> bool:
    if normalize_mime(mime) in PDF_MIME_TYPES:
        return True
    return filename.lower().endswith(".pdf")


def checksum_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checksum_meta(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def parse_sent_at(headers: dict[str, str], internal_ms: str | None) -> datetime | None:
    if internal_ms:
        try:
            return datetime.fromtimestamp(int(internal_ms) / 1000, tz=UTC)
        except (TypeError, ValueError, OSError, OverflowError):
            pass
    raw = headers.get("date")
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


@dataclass
class ParsedAttachment:
    filename: str
    mime: str
    is_pdf: bool
    size_bytes: int | None = None
    attachment_id: str | None = None
    inline_data: bytes | None = None


@dataclass
class ParsedMessage:
    gmail_id: str
    thread_id: str
    sender: str
    subject: str
    sent_at: datetime | None
    snippet: str
    body_text: str
    body_html: str | None
    label_ids: list[str] = field(default_factory=list)
    attachments: list[ParsedAttachment] = field(default_factory=list)

    @property
    def is_inbox(self) -> bool:
        return "INBOX" in set(self.label_ids)


def _walk_parts(node: dict) -> list[dict]:
    parts = node.get("parts") or []
    if not parts:
        return [node]
    found: list[dict] = []
    for part in parts:
        found.extend(_walk_parts(part))
    return found


def _collect_bodies(parts: list[dict]) -> tuple[str, str | None]:
    text_plain = ""
    text_html = ""
    for part in parts:
        mime = normalize_mime(part.get("mimeType"))
        filename = (part.get("filename") or "").strip()
        body = part.get("body") or {}
        if filename or body.get("attachmentId"):
            continue
        data = decode_gmail_data(body.get("data")).decode("utf-8", errors="replace")
        if mime == "text/plain" and data and not text_plain:
            text_plain = data
        elif mime == "text/html" and data and not text_html:
            text_html = data
    body_html = text_html or None
    body_text = text_plain.strip() or (html_to_text(text_html) if text_html else "")
    return body_text, body_html


def _collect_attachments(parts: list[dict]) -> list[ParsedAttachment]:
    attachments: list[ParsedAttachment] = []
    seen: set[str] = set()
    for part in parts:
        filename = (part.get("filename") or "").strip()
        body = part.get("body") or {}
        attachment_id = body.get("attachmentId")
        inline = decode_gmail_data(body.get("data")) if body.get("data") and filename else b""
        if not filename and not attachment_id:
            continue
        if not filename and not inline:
            continue
        mime = normalize_mime(part.get("mimeType"))
        name = filename or "attachment"
        key = f"{attachment_id or ''}:{name}:{mime}:{body.get('size')}"
        if key in seen:
            continue
        seen.add(key)
        attachments.append(
            ParsedAttachment(
                filename=name,
                mime=mime,
                is_pdf=is_pdf(name, mime),
                size_bytes=body.get("size"),
                attachment_id=attachment_id,
                inline_data=inline or None,
            )
        )
    return attachments


def parse_gmail_message(raw: dict) -> ParsedMessage:
    payload = raw.get("payload") or {}
    headers = header_map(payload)
    parts = _walk_parts(payload)
    body_text, body_html = _collect_bodies(parts)
    sender_name, sender_email = parseaddr(headers.get("from", ""))
    sender = headers.get("from") or sender_email or sender_name
    return ParsedMessage(
        gmail_id=raw.get("id") or "",
        thread_id=raw.get("threadId") or "",
        sender=sender.strip(),
        subject=(headers.get("subject") or "").strip(),
        sent_at=parse_sent_at(headers, raw.get("internalDate")),
        snippet=(raw.get("snippet") or "").strip(),
        body_text=body_text.strip(),
        body_html=body_html,
        label_ids=list(raw.get("labelIds") or []),
        attachments=_collect_attachments(parts),
    )
