"""Versioned prompt IDs, JSON schemas, and field catalogs for OpenRouter step 2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.constants import (
    CAT_ICSR,
    CAT_IRRELEVANT,
    CAT_MI,
    CAT_PQC,
    ICSR_FIELDS,
    MESSAGE_CATEGORIES,
    MI_FIELDS,
    NOT_STATED,
    PQC_FIELDS,
    PROMPT_CLASSIFY,
    PROMPT_EXTRACT_ICSR,
    PROMPT_EXTRACT_MI,
    PROMPT_EXTRACT_PQC,
    PROMPT_UNDERSTAND,
)

UNKNOWN_OVER_GUESSING = (
    "Prefer unknown over guessing. If a fact is not explicitly present in the source, "
    f'do not invent it — use "{NOT_STATED}". Never invent names, ages, dates, doses, '
    "lot numbers, outcomes, diagnoses, or countries."
)

SYSTEM_RULES = f"""You are the step-2 document understanding engine for a healthcare mailbox assistant.
You only see SYNTHETIC / made-up test data. There are no real patients.

Hard rules for every response:
- {UNKNOWN_OVER_GUESSING}
- Return JSON only. No markdown, no prose outside JSON.
- Confidence is a number from 0.0 to 1.0. Use 0.0 whenever the value is "{NOT_STATED}".
- Cite source_ref exactly as given in the pack: email:{{id}} or pdf:{{attachment_id}}:page:{{n}}.
- A quote must be a verbatim span copied from that source. If you cannot copy a span, the value is "{NOT_STATED}".
"""


def _str() -> dict[str, Any]:
    return {"type": "string"}


def _num() -> dict[str, Any]:
    return {"type": "number"}


def _bool() -> dict[str, Any]:
    return {"type": "boolean"}


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


def _arr(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


UNDERSTAND_SCHEMA = _obj(
    {
        "summary": _str(),
        "relevant": _bool(),
        "relevance_reason": _str(),
        "needs_human_review": _bool(),
        "review_reasons": _arr(_str()),
    },
    ["summary", "relevant", "relevance_reason", "needs_human_review", "review_reasons"],
)

CLASSIFY_SCHEMA = _obj(
    {
        "classifications": _arr(
            _obj(
                {
                    "category": {"type": "string", "enum": list(MESSAGE_CATEGORIES)},
                    "applies": _bool(),
                    "confidence": _num(),
                    "reason": _str(),
                },
                ["category", "applies", "confidence", "reason"],
            )
        )
    },
    ["classifications"],
)

EXTRACT_FIELD_SCHEMA = _obj(
    {
        "field": _str(),
        "value": _str(),
        "confidence": _num(),
        "source_ref": _str(),
        "quote": _str(),
    },
    ["field", "value", "confidence", "source_ref", "quote"],
)

EXTRACT_SCHEMA = _obj({"fields": _arr(EXTRACT_FIELD_SCHEMA)}, ["fields"])


@dataclass(frozen=True)
class PromptSpec:
    version: str
    schema_name: str
    schema: dict[str, Any]
    max_tokens: int = 4000


PROMPT_SPECS: dict[str, PromptSpec] = {
    PROMPT_UNDERSTAND: PromptSpec(PROMPT_UNDERSTAND, "understand", UNDERSTAND_SCHEMA, 2500),
    PROMPT_CLASSIFY: PromptSpec(PROMPT_CLASSIFY, "classify", CLASSIFY_SCHEMA, 2000),
    PROMPT_EXTRACT_ICSR: PromptSpec(PROMPT_EXTRACT_ICSR, "extract_icsr", EXTRACT_SCHEMA, 4000),
    PROMPT_EXTRACT_PQC: PromptSpec(PROMPT_EXTRACT_PQC, "extract_pqc", EXTRACT_SCHEMA, 2000),
    PROMPT_EXTRACT_MI: PromptSpec(PROMPT_EXTRACT_MI, "extract_mi", EXTRACT_SCHEMA, 2000),
}

CATEGORY_TO_EXTRACT = {
    CAT_ICSR: (PROMPT_EXTRACT_ICSR, ICSR_FIELDS),
    CAT_PQC: (PROMPT_EXTRACT_PQC, PQC_FIELDS),
    CAT_MI: (PROMPT_EXTRACT_MI, MI_FIELDS),
}

EXTRACT_FIELDS_BY_PROMPT = {
    PROMPT_EXTRACT_ICSR: ICSR_FIELDS,
    PROMPT_EXTRACT_PQC: PQC_FIELDS,
    PROMPT_EXTRACT_MI: MI_FIELDS,
}


def field_catalog_lines(fields: tuple[str, ...]) -> str:
    return "\n".join(f"- {name}" for name in fields)


def schema_is_strict(schema: dict[str, Any]) -> bool:
    if schema.get("type") != "object":
        return True
    if schema.get("additionalProperties") is not False:
        return False
    required = set(schema.get("required") or [])
    properties = schema.get("properties") or {}
    if required != set(properties):
        return False
    for value in properties.values():
        if value.get("type") == "object" and not schema_is_strict(value):
            return False
        if value.get("type") == "array" and isinstance(value.get("items"), dict):
            if not schema_is_strict(value["items"]):
                return False
    return True
