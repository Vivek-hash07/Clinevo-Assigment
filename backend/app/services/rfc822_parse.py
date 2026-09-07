"""Turn raw RFC822 bytes (as returned by IMAP FETCH) into a `ParsedMessage`.

IMAP hands back the whole MIME message, so unlike the Gmail path every attachment
is already inline and no second round-trip is needed.
"""

from __future__ import annotations

from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr

from app.services.mail_types import (
    ParsedAttachment,
    ParsedMessage,
    ParsedMessage as _ParsedMessage,
    html_to_text,
    is_pdf,
    normalize_mime,
    parse_date_header,
    snippet_from,
)

__all__ = ["parse_rfc822", "decode_mime_header"]


def decode_mime_header(value: str | None) -> str:
    """Decode RFC2047 encoded words, e.g. =?UTF-8?B?...?= in Subject / From."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return value.strip()


def _part_text(part: EmailMessage) -> str:
    try:
        payload = part.get_payload(decode=True)
    except Exception:
        return ""
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def _is_attachment(part: EmailMessage) -> bool:
    disposition = (part.get_content_disposition() or "").lower()
    if disposition == "attachment":
        return True
    # Inline parts still count when they carry a filename (common for scanned forms).
    return bool(part.get_filename())


def parse_rfc822(raw: bytes, provider_message_id: str, *, in_inbox: bool = True) -> ParsedMessage:
    message: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw)

    body_text = ""
    body_html = ""
    attachments: list[ParsedAttachment] = []

    for part in message.walk():
        if part.is_multipart():
            continue
        mime = normalize_mime(part.get_content_type())
        if _is_attachment(part):
            filename = decode_mime_header(part.get_filename()) or "attachment"
            try:
                data = part.get_payload(decode=True) or b""
            except Exception:
                data = b""
            attachments.append(
                ParsedAttachment(
                    filename=filename,
                    mime=mime,
                    is_pdf=is_pdf(filename, mime),
                    size_bytes=len(data),
                    attachment_id=None,
                    inline_data=data or None,
                )
            )
            continue
        if mime == "text/plain" and not body_text:
            body_text = _part_text(part)
        elif mime == "text/html" and not body_html:
            body_html = _part_text(part)

    if not body_text and body_html:
        body_text = html_to_text(body_html)

    raw_from = decode_mime_header(message.get("From"))
    _name, address = parseaddr(raw_from)
    sender = raw_from or address

    body_text = body_text.strip()
    return _ParsedMessage(
        provider_message_id=provider_message_id,
        # IMAP has no thread ids; References/In-Reply-To is the closest equivalent.
        thread_id=(message.get("Message-ID") or "").strip()[:255],
        sender=sender.strip()[:512],
        subject=decode_mime_header(message.get("Subject")),
        sent_at=parse_date_header(message.get("Date")),
        snippet=snippet_from(body_text),
        body_text=body_text,
        body_html=body_html or None,
        in_inbox=in_inbox,
        label_ids=[],
        attachments=attachments,
    )
