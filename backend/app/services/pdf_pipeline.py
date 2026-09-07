from __future__ import annotations

import hashlib
import io
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.constants import (
    EXTRACT_HYBRID,
    EXTRACT_LLM_FALLBACK,
    EXTRACT_PDFPLUMBER,
    EXTRACT_TESSERACT,
    EXTRACT_VISION,
    FLAVOR_HANDWRITTEN,
    FLAVOR_UNKNOWN,
    PROMPT_PDF_STEP1,
    STATUS_PENDING,
    STATUS_PROCESSING,
)
from app.models import Attachment, Message, PdfPage, PipelineRun
from app.prompts import PDF_PAGE_TEXT_V1, PDF_PAGE_VISION_V1
from app.services import storage
from app.services.audit import write_audit
from app.services.llm import LlmCompletion, LlmError, OpenRouterClient, get_llm_client
from app.services.pdf_extract import collect_signals, extract_digital_text, extract_tables, tables_look_broken
from app.services.pdf_flavor import (
    FlavorDecision,
    PageSignals,
    clamp01,
    detect_flavor,
    normalize_flavor,
    page_source_ref,
    should_rasterize,
)
from app.services.pdf_language import choose_language, detect_language_local, is_english, working_texts
from app.services.pdf_ocr import image_data_url, ocr_page, render_page

logger = logging.getLogger(__name__)


@dataclass
class PageExtract:
    page_number: int
    original_text: str
    translated_text: str | None
    text: str
    language: str
    language_confidence: float
    flavor: str
    flavor_confidence: float
    ocr_confidence: float | None
    llm_score: float | None
    extract_method: str
    column_count: int
    char_count: int
    word_count: int
    tables: list[dict[str, Any]] = field(default_factory=list)
    image_notes: list[dict[str, Any]] = field(default_factory=list)
    needs_human_review: bool = False
    review_reasons: list[str] = field(default_factory=list)
    source_ref: str = ""
    prompt_version: str = PROMPT_PDF_STEP1
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


def _fill_prompt(template: str, **fields: str) -> str:
    filled = template
    for key, value in fields.items():
        filled = filled.replace("{" + key + "}", value)
    return filled


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _token_set(text: str) -> set[str]:
    return {part for part in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if len(part) > 2}


def token_overlap(left: str, right: str) -> float:
    a = _token_set(left)
    b = _token_set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def prefer_extracted(local: str, llm_text: str, min_overlap: float) -> tuple[str, bool]:
    local_text = (local or "").strip()
    llm_clean = (llm_text or "").strip()
    if not llm_clean:
        return local_text, False
    if not local_text:
        return llm_clean, False
    overlap = token_overlap(local_text, llm_clean)
    if len(llm_clean) > 4 * max(len(local_text), 1) and overlap < min_overlap:
        return local_text, True
    return llm_clean, False


def _coerce_tables(raw: Any, source: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for table in _as_list(raw):
        if not isinstance(table, dict):
            continue
        headers = [str(cell or "") for cell in _as_list(table.get("headers"))]
        rows = []
        for row in _as_list(table.get("rows")):
            if isinstance(row, list):
                rows.append([str(cell or "") for cell in row])
        if not any(headers) and not any(any(cell.strip() for cell in row) for row in rows):
            continue
        items.append(
            {
                "caption": str(table.get("caption") or ""),
                "headers": headers,
                "rows": rows,
                "source": str(table.get("source") or source),
            }
        )
    return items


def _coerce_notes(raw: Any) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    for item in _as_list(raw):
        if not isinstance(item, dict):
            continue
        caption = str(item.get("caption") or "").strip()
        kind = str(item.get("kind") or "other").strip().lower() or "other"
        if not caption:
            continue
        notes.append(
            {
                "kind": kind[:32],
                "caption": caption[:1000],
                "needs_human_review": bool(item.get("needs_human_review", True)),
            }
        )
    return notes


def _prior_blob(signals: PageSignals, heuristic: FlavorDecision, ocr_confidence: float | None) -> str:
    return json.dumps(
        {
            "heuristic_flavor": heuristic.flavor,
            "heuristic_confidence": heuristic.confidence,
            "heuristic_reasons": heuristic.reasons,
            "char_count": signals.char_count,
            "word_count": signals.word_count,
            "image_count": signals.image_count,
            "image_area_ratio": round(signals.image_area_ratio, 4),
            "column_count": signals.column_count,
            "alphanumeric_ratio": round(signals.alphanumeric_ratio, 4),
            "ocr_confidence": ocr_confidence,
            "sample": signals.sample_text[:400],
        },
        ensure_ascii=False,
    )


def _unprocessed_pdfs(message: Message) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for attachment in message.attachments:
        if attachment.skipped or attachment.processed or not attachment.storage_key:
            continue
        mime = (attachment.mime or "").lower()
        if not (mime.startswith("application/pdf") or attachment.filename.lower().endswith(".pdf")):
            continue
        rows.append(
            {
                "id": attachment.id,
                "checksum": attachment.checksum,
                "filename": attachment.filename,
                "message_id": message.id,
                "user_id": message.user_id,
            }
        )
    return rows


def pdf_attachments_payload(message: Message) -> list[dict[str, str]]:
    return _unprocessed_pdfs(message)


def _llm_understand_page(
    client: OpenRouterClient,
    settings: Settings,
    *,
    signals: PageSignals,
    heuristic: FlavorDecision,
    local_text: str,
    ocr_text: str,
    ocr_confidence: float | None,
    local_tables: list[dict[str, Any]],
    image_url: str | None,
    use_vision: bool,
) -> LlmCompletion:
    prior = _prior_blob(signals, heuristic, ocr_confidence)
    tables_json = json.dumps(local_tables, ensure_ascii=False)[:8000]
    limit = settings.pdf_page_text_max_chars
    if use_vision and image_url:
        prompt = _fill_prompt(
            PDF_PAGE_VISION_V1,
            prior=prior,
            ocr_confidence="none" if ocr_confidence is None else f"{ocr_confidence:.2f}",
            ocr_text=_clip(ocr_text or local_text or "[no local OCR]", limit),
            local_tables=tables_json or "[]",
        )
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]
        model = settings.openrouter_vision_model or settings.openrouter_model
    else:
        prompt = _fill_prompt(
            PDF_PAGE_TEXT_V1,
            prior=prior,
            local_text=_clip(local_text, limit) or "[no local text]",
            local_tables=tables_json or "[]",
        )
        messages = [{"role": "user", "content": prompt}]
        model = settings.openrouter_model
    return client.complete_json(messages, model=model, temperature=0.0, max_tokens=4000)


def merge_page_result(
    attachment_id: str,
    page_number: int,
    signals: PageSignals,
    heuristic: FlavorDecision,
    digital_text: str,
    ocr_text: str,
    ocr_confidence: float | None,
    local_tables: list[dict[str, Any]],
    rasterized: bool,
    llm: LlmCompletion | None,
    settings: Settings,
) -> PageExtract:
    local_text = (ocr_text or digital_text).strip() if rasterized else (digital_text or ocr_text).strip()
    local_lang, local_lang_p = detect_language_local(local_text)
    data = llm.data if llm else {}

    llm_original = str(data.get("original_text_cleaned") or "").strip()
    min_overlap = settings.llm_hallucination_overlap_min
    original, hallucinated = prefer_extracted(local_text, llm_original, min_overlap)
    if not original:
        original = local_text

    language, language_confidence = choose_language(
        local_lang,
        local_lang_p,
        str(data.get("language") or "") or None,
        float(data.get("language_confidence") or 0.0),
        original,
    )
    translated = str(data.get("english_text") or "").strip() or None
    original, translated = working_texts(original, translated, language)
    english = translated or original

    llm_flavor = normalize_flavor(str(data.get("flavor") or ""), heuristic.flavor)
    llm_flavor_conf = clamp01(float(data.get("flavor_confidence") or 0.0))
    if llm and llm_flavor_conf >= 0.55:
        flavor = llm_flavor
        flavor_conf = llm_flavor_conf
    else:
        flavor = heuristic.flavor
        flavor_conf = heuristic.confidence

    llm_tables = _coerce_tables(data.get("tables"), "llm")
    tables = local_tables
    if not tables and llm_tables:
        tables = llm_tables
    elif tables_look_broken(tables) and llm_tables:
        tables = llm_tables
    image_notes = _coerce_notes(data.get("image_notes"))

    reasons = [str(item) for item in _as_list(data.get("review_reasons")) if str(item).strip()]
    needs_review = bool(data.get("needs_human_review")) if data else False
    if hallucinated:
        reasons.append("llm_text_diverged_from_local_extract")
        needs_review = True
    if flavor in {FLAVOR_HANDWRITTEN, FLAVOR_UNKNOWN}:
        needs_review = True
        reasons.append("low_certainty_page_flavor")
    if ocr_confidence is not None and ocr_confidence < settings.ocr_confidence_threshold:
        needs_review = True
        reasons.append("low_ocr_confidence")
    if image_notes and any(note.get("needs_human_review") for note in image_notes):
        needs_review = True
        reasons.append("meaningful_image")
    if not original.strip():
        needs_review = True
        reasons.append("empty_page_text")
    if not llm:
        needs_review = True
        reasons.append("llm_unavailable")

    llm_score = clamp01(float(data.get("extraction_score") or 0.0)) if data else None
    if llm_score is None:
        if original and (not rasterized or (ocr_confidence or 0) >= 0.75):
            llm_score = 0.7
        elif original:
            llm_score = 0.45
        else:
            llm_score = 0.0

    if rasterized and ocr_text and llm_original:
        method = EXTRACT_HYBRID
    elif rasterized and ocr_text and not llm:
        method = EXTRACT_TESSERACT
    elif rasterized:
        method = EXTRACT_VISION if llm else EXTRACT_TESSERACT
    elif llm and (not local_text or hallucinated is False and llm_original):
        method = EXTRACT_HYBRID if local_text else EXTRACT_LLM_FALLBACK
    else:
        method = EXTRACT_PDFPLUMBER

    column_count = signals.column_count
    layout = str(data.get("column_layout") or "")
    if layout == "multi":
        column_count = max(column_count, 2)
    elif layout == "single":
        column_count = column_count or 1

    return PageExtract(
        page_number=page_number,
        original_text=original,
        translated_text=translated,
        text=english,
        language=language,
        language_confidence=language_confidence,
        flavor=flavor,
        flavor_confidence=flavor_conf,
        ocr_confidence=ocr_confidence,
        llm_score=llm_score,
        extract_method=method,
        column_count=column_count,
        char_count=len(original),
        word_count=len(original.split()) if original else 0,
        tables=tables,
        image_notes=image_notes,
        needs_human_review=needs_review,
        review_reasons=list(dict.fromkeys(reasons)),
        source_ref=page_source_ref(attachment_id, page_number),
        prompt_version=PROMPT_PDF_STEP1,
        model=llm.model if llm else None,
        usage=dict(llm.usage) if llm else {},
    )


def inspect_pdf_attachment(attachment_id: str, run_id: str | None = None) -> dict[str, Any]:
    from app.database import session_scope

    settings = get_settings()
    started = datetime.now(UTC)
    with session_scope() as db:
        attachment = db.get(Attachment, attachment_id)
        if attachment is None:
            return {"skip": True, "reason": "missing_attachment"}
        message = db.get(Message, attachment.message_id)
        run = PipelineRun(
            run_id=run_id,
            message_id=attachment.message_id,
            function_name="pdf/process",
            started_at=started,
            status="running",
            prompt_version=PROMPT_PDF_STEP1,
        )
        db.add(run)
        db.flush()
        if attachment.skipped:
            run.status = "skipped"
            run.finished_at = datetime.now(UTC)
            return {"skip": True, "reason": "attachment_skipped"}
        if attachment.processed and attachment.pages:
            run.status = "skipped"
            run.finished_at = datetime.now(UTC)
            run.duration_ms = int((run.finished_at - started).total_seconds() * 1000)
            return {
                "skip": True,
                "reason": "already_processed",
                "page_count": attachment.page_count or len(attachment.pages),
                "message_id": attachment.message_id,
            }
        if not attachment.storage_key:
            attachment.extract_error = "missing_storage"
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            return {"skip": True, "reason": "missing_storage"}
        try:
            data = storage.read_bytes(attachment.storage_key)
        except FileNotFoundError:
            attachment.extract_error = "missing_file"
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            return {"skip": True, "reason": "missing_file", "retryable": True}

        if not data.startswith(b"%PDF"):
            attachment.extract_error = "not_a_pdf"
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            write_audit(
                db,
                "pdf.unreadable",
                message.user_id if message else None,
                {"attachment_id": attachment_id, "reason": "not_a_pdf"},
                message_id=attachment.message_id,
            )
            return {"skip": True, "reason": "not_a_pdf"}

        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(data)) as pdf:
                page_count = len(pdf.pages)
        except Exception as exc:
            attachment.extract_error = f"unreadable_pdf:{exc.__class__.__name__}"
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            write_audit(
                db,
                "pdf.unreadable",
                message.user_id if message else None,
                {"attachment_id": attachment_id, "reason": "unreadable_pdf"},
                message_id=attachment.message_id,
            )
            return {"skip": True, "reason": "unreadable_pdf"}

        if page_count <= 0:
            attachment.extract_error = "empty_pdf"
            attachment.page_count = 0
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            return {"skip": True, "reason": "empty_pdf"}

        truncated = page_count > settings.pdf_max_pages
        process_count = min(page_count, settings.pdf_max_pages)
        attachment.page_count = page_count
        attachment.extract_error = "truncated_pages" if truncated else None
        if message is not None:
            message.status = STATUS_PROCESSING
        write_audit(
            db,
            "pdf.inspect",
            message.user_id if message else None,
            {
                "attachment_id": attachment_id,
                "page_count": page_count,
                "process_count": process_count,
                "truncated": truncated,
                "input_hash": hashlib.sha256(data[: 64 * 1024]).hexdigest()[:16],
            },
            message_id=attachment.message_id,
        )
        return {
            "skip": False,
            "page_count": process_count,
            "actual_page_count": page_count,
            "truncated": truncated,
            "message_id": attachment.message_id,
            "user_id": message.user_id if message else None,
            "pipeline_run_id": run.id,
        }


def process_pdf_page(
    attachment_id: str,
    page_number: int,
    run_id: str | None = None,
) -> dict[str, Any]:
    from app.database import session_scope

    settings = get_settings()
    started = datetime.now(UTC)
    with session_scope() as db:
        attachment = db.get(Attachment, attachment_id)
        if attachment is None or not attachment.storage_key:
            return {"ok": False, "reason": "missing_attachment"}
        data = storage.read_bytes(attachment.storage_key)
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if page_number < 1 or page_number > len(pdf.pages):
                return {"ok": False, "reason": "bad_page"}
            plumber_page = pdf.pages[page_number - 1]
            signals = collect_signals(plumber_page, page_number)
            heuristic = detect_flavor(signals)
            digital_text, _method = extract_digital_text(plumber_page, signals)
            local_tables = extract_tables(plumber_page)

        rasterized = should_rasterize(signals, heuristic.flavor)
        ocr_text = ""
        ocr_confidence: float | None = None
        image_url: str | None = None
        page_image = None
        try:
            if rasterized:
                page_image = render_page(data, page_number, settings.pdf_render_scale)
                ocr = ocr_page(page_image)
                ocr_text = ocr.text
                ocr_confidence = ocr.confidence
                if heuristic.flavor == FLAVOR_UNKNOWN and ocr_confidence is not None and ocr_confidence < 0.45:
                    heuristic = FlavorDecision(FLAVOR_HANDWRITTEN, 0.55, heuristic.reasons + ["very_low_ocr"])

            llm_result: LlmCompletion | None = None
            client = get_llm_client()
            use_vision = bool(rasterized and page_image is not None)
            if client.available:
                if use_vision and page_image is not None:
                    image_url = image_data_url(page_image)
                local_for_llm = ocr_text if rasterized else digital_text
                try:
                    llm_result = _llm_understand_page(
                        client,
                        settings,
                        signals=signals,
                        heuristic=heuristic,
                        local_text=local_for_llm,
                        ocr_text=ocr_text,
                        ocr_confidence=ocr_confidence,
                        local_tables=local_tables,
                        image_url=image_url,
                        use_vision=use_vision,
                    )
                except LlmError as exc:
                    if exc.retryable:
                        raise
                    logger.warning("OpenRouter non-retryable error on page %s: %s", page_number, exc)

            merged = merge_page_result(
                attachment_id,
                page_number,
                signals,
                heuristic,
                digital_text,
                ocr_text,
                ocr_confidence,
                local_tables,
                rasterized,
                llm_result,
                settings,
            )
        finally:
            if page_image is not None:
                page_image.close()
        _upsert_page(db, attachment, merged)
        latency_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        write_audit(
            db,
            "pdf.page_extracted",
            attachment.message.user_id if attachment.message else None,
            {
                "attachment_id": attachment_id,
                "page_number": page_number,
                "flavor": merged.flavor,
                "language": merged.language,
                "extract_method": merged.extract_method,
                "ocr_confidence": merged.ocr_confidence,
                "llm_score": merged.llm_score,
                "needs_human_review": merged.needs_human_review,
                "model": merged.model,
                "usage": merged.usage,
                "latency_ms": latency_ms,
                "run_id": run_id,
                "source_ref": merged.source_ref,
            },
            message_id=attachment.message_id,
        )
        return {
            "ok": True,
            "page_number": page_number,
            "flavor": merged.flavor,
            "language": merged.language,
            "extract_method": merged.extract_method,
            "llm_score": merged.llm_score,
            "needs_human_review": merged.needs_human_review,
            "source_ref": merged.source_ref,
        }


def _upsert_page(db: Session, attachment: Attachment, extracted: PageExtract) -> PdfPage:
    existing = db.scalar(
        select(PdfPage).where(
            PdfPage.attachment_id == attachment.id,
            PdfPage.page_number == extracted.page_number,
        )
    )
    row = existing or PdfPage(attachment_id=attachment.id, page_number=extracted.page_number)
    if existing is None:
        db.add(row)
    store_limit = 200_000
    row.text = extracted.text[:store_limit]
    row.original_text = extracted.original_text[:store_limit]
    row.translated_text = extracted.translated_text[:store_limit] if extracted.translated_text else None
    row.language = extracted.language
    row.language_confidence = extracted.language_confidence
    row.ocr_confidence = extracted.ocr_confidence
    row.llm_score = extracted.llm_score
    row.flavor = extracted.flavor
    row.extract_method = extracted.extract_method
    row.column_count = extracted.column_count
    row.char_count = extracted.char_count
    row.word_count = extracted.word_count
    row.tables = extracted.tables
    row.image_notes = extracted.image_notes
    row.needs_human_review = extracted.needs_human_review
    row.review_reasons = extracted.review_reasons
    row.source_ref = extracted.source_ref
    row.prompt_version = extracted.prompt_version
    row.model = extracted.model
    db.flush()
    return row


def finalize_pdf_attachment(attachment_id: str, run_id: str | None = None) -> dict[str, Any]:
    from app.database import session_scope

    finished = datetime.now(UTC)
    with session_scope() as db:
        attachment = db.scalar(
            select(Attachment)
            .options(selectinload(Attachment.pages), selectinload(Attachment.message))
            .where(Attachment.id == attachment_id)
        )
        if attachment is None:
            return {"ok": False, "reason": "missing_attachment"}
        message = db.scalar(
            select(Message).where(Message.id == attachment.message_id).with_for_update()
        )
        flavors = [page.flavor for page in attachment.pages if page.flavor]
        attachment.document_flavor = Counter(flavors).most_common(1)[0][0] if flavors else FLAVOR_UNKNOWN
        attachment.processed = True
        attachment.processed_at = finished
        run = None
        if run_id:
            run = db.scalar(
                select(PipelineRun)
                .where(
                    PipelineRun.run_id == run_id,
                    PipelineRun.function_name == "pdf/process",
                )
                .order_by(PipelineRun.created_at.desc())
            )
        if run and run.started_at:
            attachment.duration_ms = int((finished - run.started_at).total_seconds() * 1000)
            run.finished_at = finished
            run.duration_ms = attachment.duration_ms
            run.status = "succeeded"
            run.model = next((page.model for page in attachment.pages if page.model), None)
            run.prompt_version = PROMPT_PDF_STEP1
        elif attachment.pages:
            first = min(page.created_at for page in attachment.pages if page.created_at)
            attachment.duration_ms = int((finished - first).total_seconds() * 1000)

        remaining = db.scalars(
            select(Attachment).where(
                Attachment.message_id == attachment.message_id,
                Attachment.skipped.is_(False),
                Attachment.processed.is_(False),
                Attachment.id != attachment.id,
            )
        ).all()
        still_open = []
        for item in remaining:
            mime = (item.mime or "").lower()
            if mime.startswith("application/pdf") or item.filename.lower().endswith(".pdf"):
                still_open.append(item)
        emit = not still_open
        if emit and message is not None and message.status == STATUS_PENDING:
            message.status = STATUS_PROCESSING
        write_audit(
            db,
            "pdf.processed",
            message.user_id if message else None,
            {
                "attachment_id": attachment_id,
                "page_count": len(attachment.pages),
                "document_flavor": attachment.document_flavor,
                "duration_ms": attachment.duration_ms,
                "emit_extracted": emit,
            },
            message_id=attachment.message_id,
        )
        return {
            "ok": True,
            "attachment_id": attachment_id,
            "message_id": attachment.message_id,
            "user_id": message.user_id if message else None,
            "page_count": len(attachment.pages),
            "document_flavor": attachment.document_flavor,
            "duration_ms": attachment.duration_ms,
            "emit_extracted": emit,
        }


def mark_pdf_failed(attachment_id: str, run_id: str | None, reason: str) -> dict[str, Any]:
    from app.database import session_scope

    with session_scope() as db:
        attachment = db.get(Attachment, attachment_id)
        if attachment is None:
            return {"ok": False}
        attachment.extract_error = (reason or "pdf_process_failed")[:1000]
        attachment.processed = False
        message = db.get(Message, attachment.message_id)
        remaining = db.scalars(
            select(Attachment).where(
                Attachment.message_id == attachment.message_id,
                Attachment.skipped.is_(False),
                Attachment.processed.is_(False),
            )
        ).all()
        # Leave the message pending so the reviewer queue is not stuck in processing.
        if message is not None:
            message.status = STATUS_PENDING
        if run_id:
            run = db.scalar(
                select(PipelineRun)
                .where(
                    PipelineRun.run_id == run_id,
                    PipelineRun.function_name == "pdf/process",
                )
                .order_by(PipelineRun.created_at.desc())
            )
            if run:
                run.status = "failed"
                run.finished_at = datetime.now(UTC)
                if run.started_at:
                    run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
        write_audit(
            db,
            "pdf.failed",
            message.user_id if message else None,
            {"attachment_id": attachment_id, "reason": reason, "open_pdfs": len(list(remaining))},
            message_id=attachment.message_id if attachment else None,
        )
        return {"ok": True, "reason": reason}
