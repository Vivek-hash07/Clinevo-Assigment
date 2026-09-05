from types import SimpleNamespace

from app.constants import FLAVOR_ARTICLE, FLAVOR_DIGITAL, FLAVOR_SCANNED, FLAVOR_UNKNOWN
from app.services.llm import parse_json_object
from app.services.pdf_extract import tables_look_broken
from app.services.pdf_flavor import (
    PageSignals,
    detect_flavor,
    estimate_column_count,
    page_source_ref,
    should_rasterize,
)
from app.services.pdf_language import choose_language, normalize_lang, working_texts
from app.services.pdf_pipeline import merge_page_result, prefer_extracted, token_overlap
from app.services.synthetic import build_simple_pdf


def _signals(**overrides) -> PageSignals:
    data = dict(
        page_number=1,
        width=612.0,
        height=792.0,
        char_count=400,
        word_count=80,
        line_count=20,
        image_count=0,
        image_area_ratio=0.0,
        column_count=1,
        text_density=0.01,
        alphanumeric_ratio=0.9,
        sample_text="Patient developed a rash after Examplemab.",
        has_text_layer=True,
        short_line_ratio=0.1,
    )
    data.update(overrides)
    return PageSignals(**data)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(llm_hallucination_overlap_min=0.18, ocr_confidence_threshold=0.72)


def test_flavor_digital_dense_text():
    decision = detect_flavor(_signals())
    assert decision.flavor == FLAVOR_DIGITAL
    assert decision.confidence >= 0.7


def test_flavor_scanned_image_only():
    decision = detect_flavor(
        _signals(
            char_count=8,
            word_count=1,
            has_text_layer=False,
            image_count=1,
            image_area_ratio=0.9,
            alphanumeric_ratio=0.2,
            sample_text="",
        )
    )
    assert decision.flavor == FLAVOR_SCANNED
    assert should_rasterize(
        _signals(char_count=8, has_text_layer=False, image_count=1, image_area_ratio=0.9),
        decision.flavor,
    )


def test_flavor_article_two_columns():
    decision = detect_flavor(_signals(column_count=2, char_count=900, word_count=220))
    assert decision.flavor == FLAVOR_ARTICLE


def test_column_count_from_word_mids():
    width = 600.0
    left = [80.0] * 20
    right = [480.0] * 20
    assert estimate_column_count(left + right, width) == 2
    assert estimate_column_count([300.0] * 40, width) == 1


def test_source_ref_includes_attachment_and_page():
    assert page_source_ref("att-9", 3) == "pdf:att-9:page:3"


def test_parse_json_object_strips_fences():
    payload = parse_json_object('```json\n{"flavor": "digital", "language": "en"}\n```')
    assert payload["flavor"] == "digital"


def test_fill_prompt_keeps_json_braces():
    from app.prompts import PDF_PAGE_TEXT_V1
    from app.services.pdf_pipeline import _fill_prompt

    filled = _fill_prompt(
        PDF_PAGE_TEXT_V1,
        prior='{"heuristic_flavor": "digital"}',
        local_text="Rash after Examplemab.",
        local_tables="[]",
    )
    assert "Rash after Examplemab." in filled
    assert '"flavor":' in filled
    assert "{prior}" not in filled


def test_keep_original_when_translating():
    original, translated = working_texts("El lote EX-4401 llegó dañado.", "Lot EX-4401 arrived damaged.", "es")
    assert original.startswith("El lote")
    assert translated and translated.startswith("Lot")
    original_en, translated_en = working_texts("Lot EX-4401 arrived damaged.", "Lot EX-4401 arrived damaged.", "en")
    assert translated_en is None
    assert original_en.startswith("Lot")


def test_language_prefers_llm_for_short_medical_english():
    lang, _conf = choose_language("de", 0.6, "en", 0.92, "Patient received Examplemab 40 mg.")
    assert normalize_lang(lang) == "en"


def test_prefer_extracted_rejects_invented_long_text():
    local = "Rash after Examplemab."
    invented = "The patient was hospitalized for ten days with renal failure, sepsis, and death. " * 8
    kept, flagged = prefer_extracted(local, invented, 0.18)
    assert kept == local
    assert flagged is True
    assert token_overlap(local, local) == 1.0


def test_tables_look_broken_ragged_rows():
    assert tables_look_broken(
        [{"headers": ["a", "b", "c"], "rows": [["1"], ["2", "3", "4", "5"], ["6"]]}]
    )
    assert not tables_look_broken(
        [{"headers": ["lot", "issue"], "rows": [["EX-1", "seal"], ["EX-2", "color"]]}]
    )


def test_merge_keeps_original_and_english_working_text():
    from app.services.llm import LlmCompletion
    from app.services.pdf_flavor import FlavorDecision

    llm = LlmCompletion(
        data={
            "flavor": "digital",
            "flavor_confidence": 0.9,
            "language": "es",
            "language_confidence": 0.95,
            "original_text_cleaned": "El sello estaba roto.",
            "english_text": "The seal was broken.",
            "extraction_score": 0.88,
            "needs_human_review": False,
            "review_reasons": [],
            "tables": [],
            "image_notes": [],
            "column_layout": "single",
        },
        model="test-model",
    )
    merged = merge_page_result(
        "att-1",
        2,
        _signals(char_count=22, sample_text="El sello estaba roto."),
        FlavorDecision(FLAVOR_DIGITAL, 0.8, ["dense"]),
        "El sello estaba roto.",
        "",
        None,
        [],
        False,
        llm,
        _settings(),
    )
    assert merged.original_text == "El sello estaba roto."
    assert merged.translated_text == "The seal was broken."
    assert merged.text == "The seal was broken."
    assert merged.language == "es"
    assert merged.source_ref == "pdf:att-1:page:2"
    assert merged.flavor == FLAVOR_DIGITAL


def test_merge_without_llm_flags_review():
    from app.services.pdf_flavor import FlavorDecision

    merged = merge_page_result(
        "att-2",
        1,
        _signals(),
        FlavorDecision(FLAVOR_DIGITAL, 0.8, []),
        "Fictional safety note. Patient had a rash.",
        "",
        None,
        [],
        False,
        None,
        _settings(),
    )
    assert "rash" in merged.text.lower()
    assert merged.needs_human_review
    assert "llm_unavailable" in merged.review_reasons


def test_pdfplumber_reads_synthetic_pdf():
    import io

    import pdfplumber

    blob = build_simple_pdf(
        "Fictional safety note — not a real patient",
        ["Product: Clinevo Examplemab 40 mg.", "Event: widespread rash two days after the third dose."],
    )
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        assert len(pdf.pages) == 1
        text = pdf.pages[0].extract_text() or ""
    assert "Examplemab" in text
    assert "rash" in text.lower()


def test_unknown_flavor_rasterizes():
    signals = _signals(char_count=10, has_text_layer=False, image_count=0, alphanumeric_ratio=0.0)
    assert should_rasterize(signals, FLAVOR_UNKNOWN)
