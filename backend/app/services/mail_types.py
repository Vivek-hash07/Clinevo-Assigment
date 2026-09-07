"""Provider-neutral shape of a fetched email.

Both mail providers normalize into `ParsedMessage`, so everything downstream
(ingest, PDF pipeline, AI pipeline) is unaware of whether a message arrived over
the Gmail REST API or over IMAP.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
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


def parse_date_header(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def snippet_from(body_text: str, limit: int = 300) -> str:
    collapsed = " ".join(body_text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


@dataclass
class ParsedAttachment:
    filename: str
    mime: str
    is_pdf: bool
    size_bytes: int | None = None
    # Gmail keeps large attachments behind a second API call; IMAP always inlines.
    attachment_id: str | None = None
    inline_data: bytes | None = None


@dataclass
class ParsedMessage:
    provider_message_id: str
    thread_id: str
    sender: str
    subject: str
    sent_at: datetime | None
    snippet: str
    body_text: str
    body_html: str | None
    in_inbox: bool = True
    label_ids: list[str] = field(default_factory=list)
    attachments: list[ParsedAttachment] = field(default_factory=list)
