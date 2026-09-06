from io import BytesIO

import pdfplumber

from app.constants import PROMPT_LITERATURE
from app.prompts import PROMPT_TEMPLATES
from app.services.pdf_build import build_article_pdf, build_handwritten_pdf, build_scanned_pdf, build_simple_pdf
from app.services.pdf_flavor import estimate_column_count
from app.services.synthetic import (
    catalog_coverage,
    required_coverage_ok,
    synthetic_catalog,
)


def test_day6_catalog_meets_required_counts():
    coverage = catalog_coverage()
    assert required_coverage_ok(coverage), coverage
    assert coverage["emails_with_reaction"] >= 10
    assert coverage["digital_pdfs"] >= 5
    assert coverage["scanned_or_handwritten_pdfs"] >= 2
    assert coverage["article_pdfs"] >= 5
    assert coverage["non_english_pdfs"] >= 2
    assert coverage["pqc_only"] >= 2
    assert coverage["mi_only"] >= 2
    assert coverage["irrelevant"] >= 1
    assert coverage["batch_size"] >= 10
    assert coverage["batch_size"] <= 15


def test_catalog_keys_are_unique():
    keys = [item.key for item in synthetic_catalog()]
    assert len(keys) == len(set(keys))
    assert all(item.subject.startswith("[SYNTHETIC]") or "SYNTHETIC" in item.text_body for item in synthetic_catalog())


def test_digital_pdf_has_text_layer():
    data = build_simple_pdf("Fictional title", ["Patient: Alex Rivera (made-up)", "Rash after Examplemab."])
    with pdfplumber.open(BytesIO(data)) as pdf:
        text = pdf.pages[0].extract_text() or ""
    assert "Alex Rivera" in text
    assert "SYNTHETIC" in text


def test_scanned_pdf_has_no_usable_text_layer():
    data = build_scanned_pdf("Fictional scanned card", ["Patient: Quinn Adler 72 F", "Dizziness after Exampletab"])
    with pdfplumber.open(BytesIO(data)) as pdf:
        page = pdf.pages[0]
        text = (page.extract_text() or "").strip()
        images = page.images
    assert len(text) < 40
    assert images


def test_handwritten_pdf_is_image_only():
    data = build_handwritten_pdf("Fictional card", ["Taylor Brooks age 8", "vomiting after Examplemab"])
    with pdfplumber.open(BytesIO(data)) as pdf:
        text = (pdf.pages[0].extract_text() or "").strip()
        images = pdf.pages[0].images
    assert len(text) < 40
    assert images


def test_article_pdf_is_two_columns():
    data = build_article_pdf(
        "Fictional two-column letter",
        "A. Rivera (invented)",
        "One made-up patient is described.",
        ["Case. A 54-year-old woman received Examplemab 40 mg and developed a rash two days later."] * 8,
        ["Discussion. This invented narrative exists so column detection can see a right-hand gutter."] * 8,
        ["Rivera A. Fictional Lett. 2024;1:1."],
    )
    with pdfplumber.open(BytesIO(data)) as pdf:
        page = pdf.pages[0]
        words = page.extract_words() or []
        mids = [float(word["x0"] + word["x1"]) / 2 for word in words]
        width = float(page.width)
    assert estimate_column_count(mids, width) == 2
    text = " ".join(word["text"] for word in words)
    assert "Examplemab" in text


def test_literature_prompt_is_registered():
    assert PROMPT_LITERATURE in PROMPT_TEMPLATES
    assert "identifiable patient case" in PROMPT_TEMPLATES[PROMPT_LITERATURE].lower()


def test_non_english_fixtures_exist():
    keys = {item.key for item in synthetic_catalog()}
    assert "icsr-spanish-rash" in keys
    assert "icsr-french-dyspnea" in keys
