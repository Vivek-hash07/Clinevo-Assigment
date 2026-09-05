from app.ai_contracts import (
    CLASSIFY_SCHEMA,
    EXTRACT_SCHEMA,
    PROMPT_SPECS,
    UNDERSTAND_SCHEMA,
    schema_is_strict,
)
from app.constants import (
    CAT_ICSR,
    CAT_IRRELEVANT,
    CAT_MI,
    CAT_PQC,
    ICSR_FIELDS,
    NOT_STATED,
    PROMPT_CLASSIFY,
    PROMPT_EXTRACT_ICSR,
    PROMPT_EXTRACT_MI,
    PROMPT_EXTRACT_PQC,
    PROMPT_UNDERSTAND,
)
from app.prompts import PROMPT_TEMPLATES, UNKNOWN_OVER_GUESSING
from app.services.ai_normalize import (
    coerce_classifications,
    coerce_fields,
    is_not_stated,
    locate_quote,
    normalize_category,
    select_labels,
)
from app.services.ai_pack import MessagePack, SourceSpan, parse_source_ref
from app.services.llm import OpenRouterClient


MESSAGE_ID = "11111111-1111-1111-1111-111111111111"
PDF_ID = "22222222-2222-2222-2222-222222222222"


def _pack(email_text: str, pdf_text: str | None = None) -> MessagePack:
    email_ref = f"email:{MESSAGE_ID}"
    spans = [
        SourceSpan(
            source_ref=email_ref,
            source_type="email",
            source_id=MESSAGE_ID,
            source_page=None,
            text=email_text,
        )
    ]
    allowed = {email_ref}
    if pdf_text:
        pdf_ref = f"pdf:{PDF_ID}:page:1"
        spans.append(
            SourceSpan(
                source_ref=pdf_ref,
                source_type="pdf",
                source_id=PDF_ID,
                source_page=1,
                text=pdf_text,
            )
        )
        allowed.add(pdf_ref)
    return MessagePack(
        message_id=MESSAGE_ID,
        user_id="user-1",
        status="processing",
        text=email_text,
        input_hash="abcd",
        spans=spans,
        allowed_refs=allowed,
        page_count=1 if pdf_text else 0,
    )


def test_prompt_versions_are_registered():
    assert set(PROMPT_TEMPLATES) == {
        PROMPT_UNDERSTAND,
        PROMPT_CLASSIFY,
        PROMPT_EXTRACT_ICSR,
        PROMPT_EXTRACT_PQC,
        PROMPT_EXTRACT_MI,
    }
    assert set(PROMPT_SPECS) == set(PROMPT_TEMPLATES)


def test_every_step2_prompt_prefers_unknown_over_guessing():
    assert "unknown over guessing" in UNKNOWN_OVER_GUESSING.lower()
    for version, template in PROMPT_TEMPLATES.items():
        assert "unknown over guessing" in template.lower(), version
        assert NOT_STATED in template or version == PROMPT_UNDERSTAND


def test_json_schemas_are_strict():
    for spec in PROMPT_SPECS.values():
        assert schema_is_strict(spec.schema)
    assert schema_is_strict(UNDERSTAND_SCHEMA)
    assert schema_is_strict(CLASSIFY_SCHEMA)
    assert schema_is_strict(EXTRACT_SCHEMA)


def test_openrouter_uses_json_schema_response_format():
    fmt = OpenRouterClient._response_format(CLASSIFY_SCHEMA, "classify")
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == CLASSIFY_SCHEMA
    assert OpenRouterClient._response_format(None, "x") == {"type": "json_object"}


def test_normalize_category_aliases():
    assert normalize_category("icsr") == CAT_ICSR
    assert normalize_category("Quality Complaint (PQC)") == CAT_PQC
    assert normalize_category("medical information") == CAT_MI
    assert normalize_category("spam") == CAT_IRRELEVANT
    assert normalize_category("nope") is None


def test_multi_label_keeps_icsr_and_pqc_drops_not_relevant():
    hits = coerce_classifications(
        [
            {"category": CAT_ICSR, "applies": True, "confidence": 0.91, "reason": "rash after drug"},
            {"category": CAT_PQC, "applies": True, "confidence": 0.8, "reason": "broken seal"},
            {"category": CAT_MI, "applies": False, "confidence": 0.1, "reason": "no question"},
            {"category": CAT_IRRELEVANT, "applies": True, "confidence": 0.4, "reason": "should drop"},
        ],
        0.35,
    )
    assert [hit.category for hit in hits] == [CAT_ICSR, CAT_PQC]


def test_low_confidence_label_does_not_apply():
    hits = coerce_classifications(
        [{"category": CAT_ICSR, "applies": True, "confidence": 0.2, "reason": "maybe"}],
        0.35,
    )
    assert len(hits) == 1
    assert hits[0].category == CAT_IRRELEVANT


def test_not_relevant_when_nothing_applies():
    hits = select_labels([], 0.35)
    assert hits[0].category == CAT_IRRELEVANT
    assert hits[0].applies is True


def test_missing_extract_fields_become_not_stated():
    pack = _pack("Hello, this is a marketing newsletter about a conference.")
    facts = coerce_fields(
        [{"field": "patient.age", "value": "unknown", "confidence": 0.9, "source_ref": "", "quote": ""}],
        ICSR_FIELDS,
        pack,
        8,
        PROMPT_EXTRACT_ICSR,
    )
    assert len(facts) == len(ICSR_FIELDS)
    assert all(fact.value == NOT_STATED for fact in facts)
    assert all(fact.confidence == 0.0 for fact in facts)
    assert all(fact.prompt_version == PROMPT_EXTRACT_ICSR for fact in facts)


def test_ungrounded_quote_is_forced_to_not_stated():
    pack = _pack("The bottle arrived with a broken seal on lot ZZ-1.")
    facts = coerce_fields(
        [
            {
                "field": "pqc.product",
                "value": "Examplemab",
                "confidence": 0.99,
                "source_ref": f"email:{MESSAGE_ID}",
                "quote": "Examplemab 200 mg weekly",
            }
        ],
        ("pqc.product",),
        pack,
        8,
        PROMPT_EXTRACT_PQC,
    )
    assert facts[0].value == NOT_STATED
    assert "quote_not_in_source" in facts[0].review_reasons


def test_grounded_quote_keeps_value_and_pdf_source():
    email = "Please see the attached form."
    pdf = "Patient is a 67-year-old woman who received Examplemab and developed a rash."
    pack = _pack(email, pdf)
    facts = coerce_fields(
        [
            {
                "field": "patient.age",
                "value": "67",
                "confidence": 0.86,
                "source_ref": f"email:{MESSAGE_ID}",
                "quote": "67-year-old woman",
            }
        ],
        ("patient.age",),
        pack,
        8,
        PROMPT_EXTRACT_ICSR,
    )
    assert facts[0].value == "67"
    assert facts[0].source_ref == f"pdf:{PDF_ID}:page:1"
    assert facts[0].source_page == 1
    assert "source_ref_corrected" in facts[0].review_reasons


def test_parse_source_ref():
    assert parse_source_ref(f"email:{MESSAGE_ID}") == ("email", MESSAGE_ID, None)
    assert parse_source_ref(f"pdf:{PDF_ID}:page:3") == ("pdf", PDF_ID, 3)
    assert parse_source_ref("garbage") is None


def test_locate_quote_prefers_claimed_ref():
    pack = _pack("broken seal mentioned here", "also broken seal on the form")
    span = locate_quote("broken seal", pack, f"pdf:{PDF_ID}:page:1", 8)
    assert span is not None
    assert span.source_type == "pdf"


def test_is_not_stated_aliases():
    assert is_not_stated("Unknown")
    assert is_not_stated("n/a")
    assert not is_not_stated("67 years")
    assert not is_not_stated("no")
