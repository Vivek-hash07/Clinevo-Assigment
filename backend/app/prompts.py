"""LLM prompt templates used by classify / extract (wired when those jobs run)."""

CLASSIFY_V1 = """You classify a healthcare mailbox message (email body plus all PDF text) into one or more of:

- Safety Report (ICSR)
- Quality Complaint (PQC)
- Info Request (MI)
- Not Relevant

A message may have more than one label. Never force a single category.

Return JSON only:
{
  "classifications": [
    { "category": "Safety Report (ICSR)", "confidence": 0.0, "reason": "one line" }
  ]
}

If a fact is not in the source, do not invent it. Prefer unknown over guessing.
"""

EXTRACT_ICSR_V1 = """Extract ICSR (safety report) fields from the whole message.

Groups: patient, reporter, product, reaction, severity, narrative.

Every field:
{
  "field": "patient.age",
  "value": "Not stated",
  "confidence": 0.0,
  "source": { "type": "email", "id": "...", "quote": "..." }
}

Missing facts must be "Not stated". Never invent. Unknown over guessing.
"""

EXTRACT_PQC_V1 = """Extract quality complaint (PQC) fields: product, batch/lot, defect description, photo mentioned.

Missing facts must be "Not stated". Cite email or PDF page. Never invent.
"""

EXTRACT_MI_V1 = """Extract medical information (MI) questions and the product / topic they refer to.

Missing facts must be "Not stated". Cite email or PDF page. Never invent.
"""

UNDERSTAND_V1 = """Write a 10–15 sentence reviewer summary of this message and its PDFs.

Say whether it looks relevant to patient safety, product quality, or a product question, and why.

Do not invent facts. If something is unclear, say so.
"""

PDF_STEP1_JSON_SHAPE = """
Return JSON only (no markdown) with this exact shape:
{
  "flavor": "digital|scanned|handwritten|article|form|mixed|unknown",
  "flavor_confidence": 0.0,
  "language": "en",
  "language_confidence": 0.0,
  "original_text_cleaned": "text in the original language; empty string if none",
  "english_text": "English translation of original_text_cleaned, or the same text if already English",
  "extraction_score": 0.0,
  "needs_human_review": false,
  "review_reasons": [],
  "tables": [{"caption": "", "headers": [], "rows": [[]]}],
  "image_notes": [{"kind": "photo|checkbox|diagram|logo|other", "caption": "", "needs_human_review": true}],
  "column_layout": "single|multi"
}

Rules:
- Never invent words, names, doses, lot numbers, or outcomes that are not on the page.
- If a span is unreadable, write [illegible]. Prefer unknown over guessing.
- original_text_cleaned must stay in the source language. Keep it even when you also translate.
- english_text is a faithful translation, not a summary. If the page is already English, copy original_text_cleaned.
- extraction_score is how complete and faithful the transcription is (0 = unusable, 1 = complete).
- flavor_confidence and language_confidence are 0–1.
- tables must be real row/column grids. Use [] if there is no table.
- image_notes only for meaningful pictures (damaged product, rash, filled form checkboxes), not page background.
"""

PDF_PAGE_TEXT_V1 = """You are step 1 of a healthcare mailbox PDF pipeline (synthetic / test data only).

A local extractor already ran. You must:
1. Confirm or override the page flavor.
2. Clean the extracted text without adding facts.
3. Detect language. Translate to English while keeping the original.
4. Repair tables if the local grid is empty or broken.
5. Score extraction quality.

Local detector prior (may be wrong):
{prior}

Local text (may be incomplete or noisy):
{local_text}

Local tables JSON:
{local_tables}
""" + PDF_STEP1_JSON_SHAPE

PDF_PAGE_VISION_V1 = """You are step 1 of a healthcare mailbox PDF pipeline (synthetic / test data only).

This page was rasterized because it looks scanned, handwritten, image-only, or the text layer is weak.

A local OCR engine may have produced a noisy transcript. Use the PAGE IMAGE as ground truth.
Transcribe ALL visible text in reading order. For handwriting, transcribe faithfully. If unreadable, use [illegible].

You must also: flavor, language, English translation (keep original), tables as real grids, extraction score.

Local detector prior:
{prior}

Local OCR transcript (confidence={ocr_confidence}):
{ocr_text}

Local tables JSON:
{local_tables}
""" + PDF_STEP1_JSON_SHAPE
