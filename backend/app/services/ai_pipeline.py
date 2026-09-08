"""OpenRouter step 2: understand, multi-label classify, and extract with grounding."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_contracts import (
    CATEGORY_TO_EXTRACT,
    PROMPT_SPECS,
    SYSTEM_RULES,
    PromptSpec,
)
from app.config import Settings, get_settings
from app.constants import (
    CAT_IRRELEVANT,
    NOT_STATED,
    PROMPT_CLASSIFY,
    PROMPT_UNDERSTAND,
    REVIEW_LOCK_ACTIONS,
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_READY,
    STATUS_REVIEWED,
)
from app.models import Classification, ExtractedField, Message, PipelineRun, Review
from app.prompts import PROMPT_TEMPLATES, fill_prompt
from app.services.ai_normalize import (
    ClassificationHit,
    ExtractedFact,
    coerce_classifications,
    coerce_fields,
    drop_empty_mi,
    drop_mi_if_understand_irrelevant,
)
from app.services.ai_pack import MessagePack, build_message_pack, load_message_for_ai
from app.services.audit import write_audit
from app.services.llm import LlmCompletion, LlmError, OpenRouterClient, get_llm_client

logger = logging.getLogger(__name__)


def _start_run(
    db: Session,
    *,
    function_name: str,
    message_id: str,
    prompt_version: str,
    run_id: str | None,
    started: datetime,
) -> PipelineRun:
    run = PipelineRun(
        run_id=run_id,
        message_id=message_id,
        function_name=function_name,
        started_at=started,
        status="running",
        prompt_version=prompt_version,
    )
    db.add(run)
    db.flush()
    return run


def _finish_run(
    run: PipelineRun,
    *,
    status: str,
    started: datetime,
    model: str | None = None,
) -> int:
    finished = datetime.now(UTC)
    run.finished_at = finished
    run.status = status
    if model:
        run.model = model
    duration_ms = int((finished - started).total_seconds() * 1000)
    run.duration_ms = duration_ms
    return duration_ms


def _structured_call(
    client: OpenRouterClient,
    spec: PromptSpec,
    pack_text: str,
    settings: Settings,
    **prompt_fields: str,
) -> LlmCompletion:
    template = PROMPT_TEMPLATES[spec.version]
    user = fill_prompt(template, pack=pack_text, **prompt_fields)
    return client.complete_json(
        [
            {"role": "system", "content": SYSTEM_RULES},
            {"role": "user", "content": user},
        ],
        model=settings.openrouter_model,
        temperature=0.0,
        max_tokens=spec.max_tokens,
        json_schema=spec.schema,
        schema_name=spec.schema_name,
    )


def _understand_prior(message: Message) -> str:
    if message.relevant is True:
        flag = "true"
    elif message.relevant is False:
        flag = "false"
    else:
        flag = "unknown"
    reason = (message.relevance_reason or "").strip() or "not given"
    summary = (message.summary or "").strip() or "not given"
    return f"relevant={flag}\nrelevance_reason={reason}\nsummary={summary[:1200]}"


def _pdfs_still_open(message: Message) -> bool:
    for item in message.attachments:
        if item.skipped:
            continue
        mime = (item.mime or "").lower()
        if not (mime.startswith("application/pdf") or item.filename.lower().endswith(".pdf")):
            continue
        if not item.processed:
            return True
    return False


def _protected_fields(db: Session, message_id: str) -> set[str]:
    rows = db.scalars(
        select(Review.field_name).where(
            Review.message_id == message_id,
            Review.action.in_(tuple(REVIEW_LOCK_ACTIONS)),
            Review.field_name.is_not(None),
        )
    ).all()
    return {name for name in rows if name}


def understand_message(message_id: str, run_id: str | None = None) -> dict[str, Any]:
    from app.database import session_scope

    settings = get_settings()
    started = datetime.now(UTC)
    with session_scope() as db:
        message = load_message_for_ai(db, message_id)
        run = _start_run(
            db,
            function_name="ai/understand",
            message_id=message_id,
            prompt_version=PROMPT_UNDERSTAND,
            run_id=run_id,
            started=started,
        )
        if message is None:
            _finish_run(run, status="skipped", started=started)
            return {"ok": False, "skip": True, "reason": "missing_message"}
        if message.status == STATUS_REVIEWED:
            _finish_run(run, status="skipped", started=started, model=message.ai_model)
            return {"ok": True, "skip": True, "reason": "reviewed", "message_id": message_id}
        if _pdfs_still_open(message):
            _finish_run(run, status="skipped", started=started)
            return {"ok": True, "skip": True, "reason": "pdfs_open", "message_id": message_id}
        if message.summary and message.ai_prompt_version == PROMPT_UNDERSTAND:
            _finish_run(run, status="skipped", started=started, model=message.ai_model)
            return {
                "ok": True,
                "skip": True,
                "reason": "already_understood",
                "message_id": message_id,
                "user_id": message.user_id,
            }

        pack = build_message_pack(message, settings)
        message.status = STATUS_PROCESSING
        client = get_llm_client()
        try:
            llm = _structured_call(client, PROMPT_SPECS[PROMPT_UNDERSTAND], pack.text, settings)
        except LlmError as exc:
            _finish_run(run, status="failed", started=started)
            if not exc.retryable:
                return {"ok": False, "reason": str(exc), "message_id": message.id}
            raise

        data = llm.data
        summary = str(data.get("summary") or "").strip()
        if not summary:
            raise LlmError("understand_v1 returned an empty summary", retryable=True)
        reasons = [str(item) for item in (data.get("review_reasons") or []) if str(item).strip()]
        if pack.truncated:
            reasons.append("pack_truncated")
        message.summary = summary[:20_000]
        message.relevant = bool(data.get("relevant"))
        message.relevance_reason = str(data.get("relevance_reason") or "")[:1000] or None
        message.needs_human_review = bool(data.get("needs_human_review")) or pack.truncated
        if message.needs_human_review and not reasons:
            reasons.append("model_flagged_review")
        message.ai_model = llm.model
        message.ai_prompt_version = PROMPT_UNDERSTAND
        duration_ms = _finish_run(run, status="succeeded", started=started, model=llm.model)
        write_audit(
            db,
            "ai.understood",
            message.user_id,
            {
                "prompt_version": PROMPT_UNDERSTAND,
                "model": llm.model,
                "usage": llm.usage,
                "latency_ms": llm.latency_ms,
                "duration_ms": duration_ms,
                "input_hash": pack.input_hash,
                "relevant": message.relevant,
                "needs_human_review": message.needs_human_review,
                "review_reasons": reasons,
                "truncated": pack.truncated,
                "page_count": pack.page_count,
            },
            message_id=message.id,
        )
        return {
            "ok": True,
            "message_id": message.id,
            "user_id": message.user_id,
            "relevant": message.relevant,
            "needs_human_review": message.needs_human_review,
        }


def classify_message(message_id: str, run_id: str | None = None) -> dict[str, Any]:
    from app.database import session_scope

    settings = get_settings()
    started = datetime.now(UTC)
    with session_scope() as db:
        message = load_message_for_ai(db, message_id)
        run = _start_run(
            db,
            function_name="ai/classify",
            message_id=message_id,
            prompt_version=PROMPT_CLASSIFY,
            run_id=run_id,
            started=started,
        )
        if message is None:
            _finish_run(run, status="skipped", started=started)
            return {"ok": False, "skip": True, "reason": "missing_message"}
        if message.status == STATUS_REVIEWED:
            _finish_run(run, status="skipped", started=started, model=message.ai_model)
            return {"ok": True, "skip": True, "reason": "reviewed", "message_id": message_id}

        existing = list(message.classifications)
        if existing:
            _finish_run(run, status="skipped", started=started, model=existing[0].model)
            return {
                "ok": True,
                "skip": True,
                "reason": "already_classified",
                "message_id": message_id,
                "user_id": message.user_id,
                "categories": [row.category for row in existing],
            }

        pack = build_message_pack(message, settings)
        message.status = STATUS_PROCESSING
        client = get_llm_client()
        try:
            llm = _structured_call(
                client,
                PROMPT_SPECS[PROMPT_CLASSIFY],
                pack.text,
                settings,
                understand_prior=_understand_prior(message),
            )
        except LlmError as exc:
            _finish_run(run, status="failed", started=started)
            if not exc.retryable:
                return {"ok": False, "reason": str(exc), "message_id": message.id}
            raise

        hits = coerce_classifications(llm.data.get("classifications"), settings.ai_classify_min_confidence)
        hits = drop_mi_if_understand_irrelevant(hits, message.relevant)
        _upsert_classifications(db, message, hits, llm.model)
        if any(hit.category != CAT_IRRELEVANT for hit in hits):
            message.relevant = True
        elif message.relevant is None:
            message.relevant = False
        duration_ms = _finish_run(run, status="succeeded", started=started, model=llm.model)
        write_audit(
            db,
            "ai.classified",
            message.user_id,
            {
                "prompt_version": PROMPT_CLASSIFY,
                "model": llm.model,
                "usage": llm.usage,
                "latency_ms": llm.latency_ms,
                "duration_ms": duration_ms,
                "input_hash": pack.input_hash,
                "labels": [
                    {"category": hit.category, "confidence": hit.confidence, "reason": hit.reason}
                    for hit in hits
                ],
            },
            message_id=message.id,
        )
        return {
            "ok": True,
            "message_id": message.id,
            "user_id": message.user_id,
            "categories": [hit.category for hit in hits],
        }


def extract_facts(message_id: str, run_id: str | None = None) -> dict[str, Any]:
    from app.database import session_scope

    settings = get_settings()
    started = datetime.now(UTC)
    with session_scope() as db:
        message = load_message_for_ai(db, message_id)
        run = _start_run(
            db,
            function_name="ai/extract",
            message_id=message_id,
            prompt_version="extract_v1",
            run_id=run_id,
            started=started,
        )
        if message is None:
            _finish_run(run, status="skipped", started=started)
            return {"ok": False, "skip": True, "reason": "missing_message"}
        if message.status == STATUS_REVIEWED:
            _finish_run(run, status="skipped", started=started, model=message.ai_model)
            return {"ok": True, "skip": True, "reason": "reviewed", "message_id": message_id}

        labels = [row.category for row in message.classifications]
        extractable = [cat for cat in labels if cat in CATEGORY_TO_EXTRACT]
        if extractable:
            run.prompt_version = ",".join(CATEGORY_TO_EXTRACT[cat][0] for cat in extractable)
        if message.extracted_fields and not extractable:
            message.status = STATUS_READY
            message.ai_completed_at = datetime.now(UTC)
            _finish_run(run, status="skipped", started=started, model=message.ai_model)
            from app.services.literature import should_auto_screen

            return {
                "ok": True,
                "skip": True,
                "reason": "already_extracted",
                "message_id": message_id,
                "user_id": message.user_id,
                "screen_literature": should_auto_screen(message),
            }
        if message.extracted_fields and extractable:
            expected = {name for cat in extractable for name in CATEGORY_TO_EXTRACT[cat][1]}
            have = {row.field for row in message.extracted_fields}
            if expected <= have:
                message.status = STATUS_READY
                if message.ai_completed_at is None:
                    message.ai_completed_at = datetime.now(UTC)
                _finish_run(run, status="skipped", started=started, model=message.ai_model)
                from app.services.literature import should_auto_screen

                return {
                    "ok": True,
                    "skip": True,
                    "reason": "already_extracted",
                    "message_id": message_id,
                    "user_id": message.user_id,
                    "field_count": len(message.extracted_fields),
                    "screen_literature": should_auto_screen(message),
                }

        pack = build_message_pack(message, settings)
        message.status = STATUS_PROCESSING
        client = get_llm_client()
        facts: list[ExtractedFact] = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        models: list[str] = []
        ungrounded = 0
        try:
            for category in extractable:
                version, catalog = CATEGORY_TO_EXTRACT[category]
                llm = _structured_call(client, PROMPT_SPECS[version], pack.text, settings)
                models.append(llm.model)
                for key in usage:
                    usage[key] += int(llm.usage.get(key) or 0)
                group = coerce_fields(
                    llm.data.get("fields"),
                    catalog,
                    pack,
                    settings.ai_quote_min_chars,
                    version,
                )
                ungrounded += sum(1 for fact in group if "quote_not_in_source" in fact.review_reasons)
                facts.extend(group)
        except LlmError as exc:
            _finish_run(run, status="failed", started=started)
            if not exc.retryable:
                return {"ok": False, "reason": str(exc), "message_id": message.id}
            raise

        locked = _protected_fields(db, message.id)
        labels = [row.category for row in message.classifications]
        hits = [
            ClassificationHit(row.category, True, float(row.confidence or 0.0), row.reason or "")
            for row in message.classifications
        ]
        hits, facts, mi_demoted = drop_empty_mi(hits, facts)
        if mi_demoted:
            _upsert_classifications(db, message, hits, models[-1] if models else None)
            labels = [hit.category for hit in hits]
            if all(hit.category == CAT_IRRELEVANT for hit in hits):
                message.relevant = False
            _clear_fields_not_in(db, message, {fact.field for fact in facts}, locked)
        _upsert_fields(db, message, facts, models[-1] if models else None, locked)
        if ungrounded:
            message.needs_human_review = True
        message.status = STATUS_READY
        message.ai_completed_at = datetime.now(UTC)
        if models:
            message.ai_model = models[-1]
        duration_ms = _finish_run(run, status="succeeded", started=started, model=models[-1] if models else None)
        write_audit(
            db,
            "ai.extracted",
            message.user_id,
            {
                "prompt_versions": [CATEGORY_TO_EXTRACT[cat][0] for cat in extractable],
                "model": models[-1] if models else None,
                "usage": usage,
                "duration_ms": duration_ms,
                "input_hash": pack.input_hash,
                "field_count": len(facts),
                "not_stated_count": sum(1 for fact in facts if fact.value == NOT_STATED),
                "ungrounded_count": ungrounded,
                "locked_fields": sorted(locked),
                "categories": labels,
                "mi_demoted": mi_demoted,
            },
            message_id=message.id,
        )
        from app.services.literature import should_auto_screen

        return {
            "ok": True,
            "message_id": message.id,
            "user_id": message.user_id,
            "categories": labels,
            "field_count": len(facts),
            "not_stated_count": sum(1 for fact in facts if fact.value == NOT_STATED),
            "mi_demoted": mi_demoted,
            "screen_literature": should_auto_screen(message),
        }


def mark_ai_failed(message_id: str, run_id: str | None, reason: str) -> dict[str, Any]:
    from app.database import session_scope

    with session_scope() as db:
        message = db.get(Message, message_id)
        if message is None:
            return {"ok": False}
        if message.status != STATUS_REVIEWED:
            message.status = STATUS_PENDING
            message.needs_human_review = True
        if run_id:
            run = db.scalar(
                select(PipelineRun)
                .where(
                    PipelineRun.run_id == run_id,
                    PipelineRun.function_name.in_(("ai/understand", "ai/classify", "ai/extract")),
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
            "ai.failed",
            message.user_id,
            {"reason": reason, "run_id": run_id},
            message_id=message.id,
        )
        return {"ok": True, "reason": reason}


def _clear_fields_not_in(
    db: Session,
    message: Message,
    keep: set[str],
    locked: set[str],
) -> None:
    leftover = [row for row in list(message.extracted_fields) if row.field not in keep and row.field not in locked]
    for row in leftover:
        db.delete(row)
        message.extracted_fields.remove(row)


def _upsert_classifications(
    db: Session,
    message: Message,
    hits: list[ClassificationHit],
    model: str | None,
) -> None:
    existing = {row.category: row for row in message.classifications}
    keep = {hit.category for hit in hits}
    for hit in hits:
        row = existing.get(hit.category) or Classification(message_id=message.id, category=hit.category)
        if hit.category not in existing:
            db.add(row)
            message.classifications.append(row)
        row.confidence = hit.confidence
        row.reason = hit.reason or ""
        row.prompt_version = PROMPT_CLASSIFY
        row.model = model
    for category, row in existing.items():
        if category not in keep:
            db.delete(row)
            if row in message.classifications:
                message.classifications.remove(row)


def _upsert_fields(
    db: Session,
    message: Message,
    facts: list[ExtractedFact],
    model: str | None,
    locked: set[str],
) -> None:
    existing = {row.field: row for row in message.extracted_fields}
    for fact in facts:
        if fact.field in locked:
            continue
        row = existing.get(fact.field) or ExtractedField(message_id=message.id, field=fact.field)
        if fact.field not in existing:
            db.add(row)
            message.extracted_fields.append(row)
        row.value = fact.value
        row.confidence = fact.confidence
        row.source_type = fact.source_type
        row.source_id = fact.source_id
        row.source_quote = fact.quote or None
        row.source_page = fact.source_page
        row.source_ref = fact.source_ref
        row.prompt_version = fact.prompt_version or None
        row.model = model
        existing[fact.field] = row
