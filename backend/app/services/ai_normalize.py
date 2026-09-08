"""Coerce structured LLM output: multi-label rules, Not stated, quote grounding."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.constants import (
    CAT_ICSR,
    CAT_IRRELEVANT,
    CAT_MI,
    CAT_PQC,
    DERIVED_FIELDS,
    MESSAGE_CATEGORIES,
    MI_FIELDS,
    NOT_STATED,
)
from app.services.ai_pack import MessagePack, SourceSpan, parse_source_ref
from app.services.pdf_flavor import clamp01

_WS = re.compile(r"\s+")
_NOT_STATED_ALIASES = frozenset(
    {
        "",
        "not stated",
        "unknown",
        "n/a",
        "na",
        "unspecified",
        "not mentioned",
        "not provided",
        "not reported",
        "not available",
    }
)

_CATEGORY_ALIASES = {
    "icsr": CAT_ICSR,
    "safety": CAT_ICSR,
    "safety report": CAT_ICSR,
    "safety report (icsr)": CAT_ICSR,
    "adverse event": CAT_ICSR,
    "ae": CAT_ICSR,
    "pqc": CAT_PQC,
    "quality": CAT_PQC,
    "quality complaint": CAT_PQC,
    "quality complaint (pqc)": CAT_PQC,
    "product quality": CAT_PQC,
    "mi": CAT_MI,
    "info request": CAT_MI,
    "info request (mi)": CAT_MI,
    "medical information": CAT_MI,
    "information request": CAT_MI,
    "not relevant": CAT_IRRELEVANT,
    "irrelevant": CAT_IRRELEVANT,
    "spam": CAT_IRRELEVANT,
    "other": CAT_IRRELEVANT,
}


@dataclass
class ClassificationHit:
    category: str
    applies: bool
    confidence: float
    reason: str


@dataclass
class ExtractedFact:
    field: str
    value: str
    confidence: float
    source_ref: str
    quote: str
    source_type: str | None = None
    source_id: str | None = None
    source_page: int | None = None
    grounded: bool = True
    review_reasons: list[str] = field(default_factory=list)
    prompt_version: str = ""


def normalize_ws(text: str) -> str:
    return _WS.sub(" ", (text or "").strip())


def is_not_stated(value: str | None) -> bool:
    return normalize_ws(value or "").lower() in _NOT_STATED_ALIASES


def canonical_not_stated(value: str | None) -> str:
    if is_not_stated(value):
        return NOT_STATED
    return normalize_ws(value or "") or NOT_STATED


def normalize_category(value: str | None) -> str | None:
    raw = normalize_ws(value or "").lower()
    if not raw:
        return None
    if value in MESSAGE_CATEGORIES:
        return value
    return _CATEGORY_ALIASES.get(raw)


def quote_in_text(quote: str, text: str, min_chars: int) -> bool:
    needle = normalize_ws(quote).lower()
    hay = normalize_ws(text).lower()
    if len(needle) < min_chars:
        return False
    if needle in hay:
        return True
    compact_q = needle.replace(" ", "")
    compact_h = hay.replace(" ", "")
    return len(compact_q) >= min_chars and compact_q in compact_h


def locate_quote(
    quote: str,
    pack: MessagePack,
    preferred_ref: str | None,
    min_chars: int,
) -> SourceSpan | None:
    matches = [span for span in pack.spans if quote_in_text(quote, span.text, min_chars)]
    if not matches:
        return None
    if preferred_ref:
        for span in matches:
            if span.source_ref == preferred_ref:
                return span
    return matches[0]


def coerce_classifications(raw: object, min_confidence: float) -> list[ClassificationHit]:
    items: list[ClassificationHit] = []
    rows = raw if isinstance(raw, list) else []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        category = normalize_category(str(row.get("category") or ""))
        if category is None or category in seen:
            continue
        seen.add(category)
        try:
            confidence = clamp01(float(row.get("confidence") or 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if "applies" in row:
            applies = bool(row.get("applies")) and confidence >= min_confidence
        else:
            applies = confidence >= min_confidence
        reason = normalize_ws(str(row.get("reason") or ""))[:500]
        items.append(ClassificationHit(category, applies, confidence, reason))
    return select_labels(items, min_confidence)


def select_labels(items: list[ClassificationHit], min_confidence: float) -> list[ClassificationHit]:
    by_cat = {item.category: item for item in items}
    relevant: list[ClassificationHit] = []
    for category in (CAT_ICSR, CAT_PQC, CAT_MI):
        hit = by_cat.get(category)
        if hit and hit.applies and hit.confidence >= min_confidence:
            relevant.append(hit)
    if relevant:
        return relevant
    fallback = by_cat.get(CAT_IRRELEVANT)
    reason = fallback.reason if fallback and fallback.reason else "No ICSR, PQC, or MI evidence in the source."
    confidence = fallback.confidence if fallback else 0.5
    if confidence < 0.5:
        confidence = 0.5
    return [ClassificationHit(CAT_IRRELEVANT, True, confidence, reason)]


def not_relevant_hit(reason: str, confidence: float = 0.7) -> ClassificationHit:
    return ClassificationHit(CAT_IRRELEVANT, True, max(confidence, 0.5), reason)


def drop_mi_if_understand_irrelevant(
    hits: list[ClassificationHit],
    relevant: bool | None,
) -> list[ClassificationHit]:
    """Understand already said this is not ICSR/PQC/MI. Keep safety/quality; drop false MI."""
    if relevant is not False:
        return hits
    if not any(hit.category == CAT_MI for hit in hits):
        return hits
    kept = [hit for hit in hits if hit.category != CAT_MI]
    if any(hit.category in (CAT_ICSR, CAT_PQC) for hit in kept):
        return kept
    return [
        not_relevant_hit(
            "Understand step found no safety report, quality complaint, or medical-product question."
        )
    ]


def drop_empty_mi(
    hits: list[ClassificationHit],
    facts: list[ExtractedFact],
) -> tuple[list[ClassificationHit], list[ExtractedFact], bool]:
    """MI with no extractable product question is a false positive (surveys, course mail)."""
    if not any(hit.category == CAT_MI for hit in hits):
        return hits, facts, False
    questions = next((fact for fact in facts if fact.field == "mi.questions"), None)
    if questions is not None and not is_not_stated(questions.value):
        return hits, facts, False
    remaining_hits = [hit for hit in hits if hit.category != CAT_MI]
    remaining_facts = [fact for fact in facts if fact.field not in MI_FIELDS]
    if not remaining_hits:
        remaining_hits = [
            not_relevant_hit("No extractable medical-information question about a product.")
        ]
    return remaining_hits, remaining_facts, True


def empty_fact(field_name: str, email_ref: str, reason: str, prompt_version: str = "") -> ExtractedFact:
    parsed = parse_source_ref(email_ref)
    return ExtractedFact(
        field=field_name,
        value=NOT_STATED,
        confidence=0.0,
        source_ref=email_ref,
        quote="",
        source_type=parsed[0] if parsed else "email",
        source_id=parsed[1] if parsed else None,
        source_page=parsed[2] if parsed else None,
        grounded=True,
        review_reasons=[reason] if reason else [],
        prompt_version=prompt_version,
    )


def coerce_fields(
    raw: object,
    catalog: tuple[str, ...],
    pack: MessagePack,
    min_quote_chars: int,
    prompt_version: str = "",
) -> list[ExtractedFact]:
    email_ref = f"email:{pack.message_id}"
    by_name: dict[str, dict] = {}
    rows = raw if isinstance(raw, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("field") or "").strip()
        if name in catalog and name not in by_name:
            by_name[name] = row
    facts: list[ExtractedFact] = []
    for name in catalog:
        row = by_name.get(name)
        if row is None:
            facts.append(empty_fact(name, email_ref, "model_omitted_field", prompt_version))
            continue
        facts.append(ground_fact(name, row, pack, min_quote_chars, email_ref, prompt_version))
    return facts


def ground_fact(
    field_name: str,
    row: dict,
    pack: MessagePack,
    min_quote_chars: int,
    email_ref: str,
    prompt_version: str = "",
) -> ExtractedFact:
    value = canonical_not_stated(str(row.get("value") if row.get("value") is not None else ""))
    quote = normalize_ws(str(row.get("quote") or ""))
    claimed_ref = str(row.get("source_ref") or "").strip()
    try:
        confidence = clamp01(float(row.get("confidence") or 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    reasons: list[str] = []

    if value == NOT_STATED:
        parsed = parse_source_ref(claimed_ref) if claimed_ref in pack.allowed_refs else parse_source_ref(email_ref)
        return ExtractedFact(
            field=field_name,
            value=NOT_STATED,
            confidence=0.0,
            source_ref=(claimed_ref if claimed_ref in pack.allowed_refs else email_ref),
            quote="",
            source_type=parsed[0] if parsed else "email",
            source_id=parsed[1] if parsed else pack.message_id,
            source_page=parsed[2] if parsed else None,
            grounded=True,
            review_reasons=[],
            prompt_version=prompt_version,
        )

    if field_name in DERIVED_FIELDS:
        parsed = parse_source_ref(claimed_ref) if claimed_ref in pack.allowed_refs else parse_source_ref(email_ref)
        return ExtractedFact(
            field=field_name,
            value=value[:4000],
            confidence=max(confidence, 0.4) if value else 0.0,
            source_ref=claimed_ref if claimed_ref in pack.allowed_refs else email_ref,
            quote=quote[:1000],
            source_type=parsed[0] if parsed else "email",
            source_id=parsed[1] if parsed else pack.message_id,
            source_page=parsed[2] if parsed else None,
            grounded=True,
            review_reasons=[],
            prompt_version=prompt_version,
        )

    span = locate_quote(quote, pack, claimed_ref if claimed_ref in pack.allowed_refs else None, min_quote_chars)
    if span is None:
        reasons.append("quote_not_in_source")
        return empty_fact(field_name, email_ref, "quote_not_in_source", prompt_version)

    parsed = parse_source_ref(span.source_ref)
    if claimed_ref and claimed_ref != span.source_ref:
        reasons.append("source_ref_corrected")
    return ExtractedFact(
        field=field_name,
        value=value[:2000],
        confidence=confidence if confidence > 0 else 0.5,
        source_ref=span.source_ref,
        quote=quote[:1000],
        source_type=parsed[0] if parsed else span.source_type,
        source_id=parsed[1] if parsed else span.source_id,
        source_page=parsed[2] if parsed else span.source_page,
        grounded=True,
        review_reasons=reasons,
        prompt_version=prompt_version,
    )
