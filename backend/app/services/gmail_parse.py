"""Turn a Gmail REST `Message` resource (format=full) into a `ParsedMessage`."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from email.utils import parseaddr

from app.services.mail_types import (
    ParsedAttachment,
    ParsedMessage,
    checksum_bytes,
    checksum_meta,
    html_to_text,
    is_pdf,
    normalize_mime,
    parse_date_header,
)

__all__ = [
    "ParsedAttachment",
    "ParsedMessage",
    "checksum_bytes",
    "checksum_meta",
    "decode_gmail_data",
    "header_map",
    "parse_gmail_message",
    "parse_sent_at",
]


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


def parse_sent_at(headers: dict[str, str], internal_ms: str | None) -> datetime | None:
    if internal_ms:
        try:
            return datetime.fromtimestamp(int(internal_ms) / 1000, tz=UTC)
        except (TypeError, ValueError, OSError, OverflowError):
            pass
    return parse_date_header(headers.get("date"))


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
    label_ids = list(raw.get("labelIds") or [])
    return ParsedMessage(
        provider_message_id=raw.get("id") or "",
        thread_id=raw.get("threadId") or "",
        sender=sender.strip(),
        subject=(headers.get("subject") or "").strip(),
        sent_at=parse_sent_at(headers, raw.get("internalDate")),
        snippet=(raw.get("snippet") or "").strip(),
        body_text=body_text.strip(),
        body_html=body_html,
        in_inbox="INBOX" in set(label_ids),
        label_ids=label_ids,
        attachments=_collect_attachments(parts),
    )
