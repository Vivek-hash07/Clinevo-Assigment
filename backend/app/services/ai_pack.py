"""Assemble a whole-message pack so classify/extract cite email or PDF page."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.models import Attachment, Message, PdfPage

EMAIL_REF = re.compile(r"^email:([0-9a-fA-F-]{36})$")
PDF_REF = re.compile(r"^pdf:([0-9a-fA-F-]{36}):page:(\d+)$")


@dataclass(frozen=True)
class SourceSpan:
    source_ref: str
    source_type: str
    source_id: str
    source_page: int | None
    text: str


@dataclass
class MessagePack:
    message_id: str
    user_id: str
    status: str
    text: str
    input_hash: str
    spans: list[SourceSpan] = field(default_factory=list)
    allowed_refs: set[str] = field(default_factory=set)
    page_count: int = 0
    truncated: bool = False


def email_source_ref(message_id: str) -> str:
    return f"email:{message_id}"


def parse_source_ref(value: str) -> tuple[str, str, int | None] | None:
    raw = (value or "").strip()
    email = EMAIL_REF.match(raw)
    if email:
        return "email", email.group(1), None
    pdf = PDF_REF.match(raw)
    if pdf:
        return "pdf", pdf.group(1), int(pdf.group(2))
    return None


def _clip(text: str, limit: int) -> tuple[str, bool]:
    raw = text or ""
    if len(raw) <= limit:
        return raw, False
    return raw[: max(limit - 1, 0)] + "…", True


def _page_block(page: PdfPage, limit: int) -> tuple[str, bool]:
    bits = [
        f"PAGE {page.page_number} source_ref={page.source_ref or ''}",
        f"flavor={page.flavor or 'unknown'} language={page.language or 'und'} "
        f"ocr_confidence={page.ocr_confidence} llm_score={page.llm_score}",
    ]
    if page.needs_human_review:
        bits.append("needs_human_review=true reasons=" + ",".join(page.review_reasons or []))
    body = (page.text or page.translated_text or page.original_text or "").strip()
    body, clipped = _clip(body, limit)
    bits.append(body or "[no text on this page]")
    if page.original_text and page.translated_text and page.original_text.strip() != page.translated_text.strip():
        original, orig_clip = _clip(page.original_text.strip(), min(limit, 2000))
        bits.append("ORIGINAL_LANGUAGE_TEXT:")
        bits.append(original)
        clipped = clipped or orig_clip
    if page.tables:
        table_json, table_clip = _clip(json.dumps(page.tables, ensure_ascii=False), 4000)
        bits.append("TABLES_JSON:")
        bits.append(table_json)
        clipped = clipped or table_clip
    if page.image_notes:
        notes, note_clip = _clip(json.dumps(page.image_notes, ensure_ascii=False), 1500)
        bits.append("IMAGE_NOTES_JSON:")
        bits.append(notes)
        clipped = clipped or note_clip
    return "\n".join(bits), clipped


def _span_text(page: PdfPage) -> str:
    parts = [page.text or "", page.translated_text or "", page.original_text or ""]
    if page.tables:
        parts.append(json.dumps(page.tables, ensure_ascii=False))
    if page.image_notes:
        parts.append(json.dumps(page.image_notes, ensure_ascii=False))
    return "\n".join(part for part in parts if part)


def load_message_for_ai(db: Session, message_id: str) -> Message | None:
    return db.scalar(
        selectinload_message(message_id)
    )


def selectinload_message(message_id: str):
    from sqlalchemy import select

    return (
        select(Message)
        .options(
            selectinload(Message.attachments).selectinload(Attachment.pages),
            selectinload(Message.classifications),
            selectinload(Message.extracted_fields),
        )
        .where(Message.id == message_id)
    )


def build_message_pack(message: Message, settings: Settings | None = None) -> MessagePack:
    cfg = settings or get_settings()
    email_ref = email_source_ref(message.id)
    email_body, email_clipped = _clip(message.body or "", cfg.ai_email_max_chars)
    header = [
        f"MESSAGE_ID={message.id}",
        f"source_ref={email_ref}",
        f"from={message.sender}",
        f"subject={message.subject}",
        f"sent_at={message.sent_at.isoformat() if message.sent_at else ''}",
        "EMAIL_BODY:",
        email_body or "[empty body]",
    ]
    spans = [
        SourceSpan(
            source_ref=email_ref,
            source_type="email",
            source_id=message.id,
            source_page=None,
            text="\n".join([message.subject or "", message.sender or "", message.body or ""]),
        )
    ]
    allowed = {email_ref}
    truncated = email_clipped
    page_count = 0
    chunks = ["\n".join(header)]
    used = len(chunks[0])

    pdfs = [
        item
        for item in message.attachments
        if not item.skipped
        and (
            (item.mime or "").lower().startswith("application/pdf")
            or item.filename.lower().endswith(".pdf")
        )
    ]
    for attachment in pdfs:
        pages = sorted(attachment.pages, key=lambda row: row.page_number)
        intro = (
            f"PDF filename={attachment.filename} attachment_id={attachment.id} "
            f"flavor={attachment.document_flavor or 'unknown'} pages={len(pages)}"
        )
        chunks.append(intro)
        used += len(intro) + 1
        for page in pages:
            page_count += 1
            ref = page.source_ref or f"pdf:{attachment.id}:page:{page.page_number}"
            allowed.add(ref)
            spans.append(
                SourceSpan(
                    source_ref=ref,
                    source_type="pdf",
                    source_id=attachment.id,
                    source_page=page.page_number,
                    text=_span_text(page),
                )
            )
            if used >= cfg.ai_pack_max_chars:
                truncated = True
                continue
            block, clipped = _page_block(page, cfg.ai_page_max_chars)
            room = cfg.ai_pack_max_chars - used
            if len(block) > room:
                block = block[: max(room - 1, 0)] + "…"
                truncated = True
            chunks.append(block)
            used += len(block) + 1
            truncated = truncated or clipped

    if truncated:
        chunks.append("[PACK TRUNCATED — cite only sources that appear above]")
    text = "\n\n".join(chunks)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return MessagePack(
        message_id=message.id,
        user_id=message.user_id,
        status=message.status,
        text=text,
        input_hash=digest,
        spans=spans,
        allowed_refs=allowed,
        page_count=page_count,
        truncated=truncated,
    )
