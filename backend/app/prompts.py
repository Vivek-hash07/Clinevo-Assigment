"""Versioned LLM prompt templates. IDs match constants (classify_v1, extract_icsr_v1, …)."""

from app.ai_contracts import UNKNOWN_OVER_GUESSING, field_catalog_lines
from app.constants import (
    CAT_ICSR,
    CAT_IRRELEVANT,
    CAT_MI,
    CAT_PQC,
    ICSR_FIELDS,
    MI_FIELDS,
    NOT_STATED,
    PQC_FIELDS,
    PROMPT_LITERATURE,
)


def fill_prompt(template: str, **fields: str) -> str:
    filled = template
    for key, value in fields.items():
        filled = filled.replace("{" + key + "}", value)
    return filled


CLASSIFY_V1 = f"""Prompt version: classify_v1

Classify the WHOLE mailbox message (email body plus every PDF page in the pack) into the four
categories below. This is multi-label: a message may belong to more than one category at the same
time. Never force a single label. Decide each category independently.

Categories:
- {CAT_ICSR}: a person had a suspected adverse reaction / bad outcome involving a product (patient +
  product + event, even loosely).
- {CAT_PQC}: something is physically wrong with the product (broken seal, wrong color, contamination,
  damaged packaging, counterfeit, missing tablets).
- {CAT_MI}: a question about a product (dosing, how to take it, interactions) with no reaction and
  no product defect.
- {CAT_IRRELEVANT}: marketing, spam, internal admin, or anything that is none of the above.

Return JSON only with this shape:
{{
  "classifications": [
    {{ "category": "{CAT_ICSR}", "applies": true, "confidence": 0.0, "reason": "one line" }},
    {{ "category": "{CAT_PQC}", "applies": false, "confidence": 0.0, "reason": "one line" }},
    {{ "category": "{CAT_MI}", "applies": false, "confidence": 0.0, "reason": "one line" }},
    {{ "category": "{CAT_IRRELEVANT}", "applies": false, "confidence": 0.0, "reason": "one line" }}
  ]
}}

Rules:
- Include exactly one object for each of the four categories.
- applies=true only when the source supports that category. Do not guess.
- reason must be one sentence pointing at evidence in the pack (or stating that none exists).
- If any of ICSR / PQC / MI applies, Not Relevant must have applies=false.
- If none of ICSR / PQC / MI applies, Not Relevant must have applies=true.
- {UNKNOWN_OVER_GUESSING}

Message pack:
{{pack}}
"""

EXTRACT_ICSR_V1 = f"""Prompt version: extract_icsr_v1

Extract ICSR (safety report) fields from the WHOLE message pack. Return every field in the catalog,
even when missing.

Field catalog:
{field_catalog_lines(ICSR_FIELDS)}

Return JSON only:
{{
  "fields": [
    {{
      "field": "patient.age",
      "value": "{NOT_STATED}",
      "confidence": 0.0,
      "source_ref": "email:MESSAGE_ID",
      "quote": ""
    }}
  ]
}}

Rules:
- One object per catalog field. Do not add extra fields. Do not omit any catalog field.
- value is a short string copied or faithfully condensed from the source. If it is not in the source,
  value MUST be "{NOT_STATED}" and confidence MUST be 0.0 and quote MUST be "".
- quote is a verbatim excerpt from the cited source_ref. Empty when value is "{NOT_STATED}".
- source_ref must be one of the refs in the pack (email:… or pdf:…:page:…).
- narrative.summary is a short case narrative using ONLY facts that appear in the pack. If the pack
  is too thin, say so inside the narrative; still do not invent.
- {UNKNOWN_OVER_GUESSING}

Message pack:
{{pack}}
"""

EXTRACT_PQC_V1 = f"""Prompt version: extract_pqc_v1

Extract quality complaint (PQC) fields from the WHOLE message pack. Return every catalog field.

Field catalog:
{field_catalog_lines(PQC_FIELDS)}

- pqc.product: product name.
- pqc.batch_lot: batch / lot / serial if stated.
- pqc.defect: what is physically wrong.
- pqc.photo_mentioned: "yes" or "no" only if the source says a photo exists or does not; otherwise
  "{NOT_STATED}".

Return JSON only:
{{
  "fields": [
    {{
      "field": "pqc.product",
      "value": "{NOT_STATED}",
      "confidence": 0.0,
      "source_ref": "email:MESSAGE_ID",
      "quote": ""
    }}
  ]
}}

Rules:
- One object per catalog field. Never invent batch/lot numbers.
- Missing facts MUST be "{NOT_STATED}" with confidence 0.0 and an empty quote.
- {UNKNOWN_OVER_GUESSING}

Message pack:
{{pack}}
"""

EXTRACT_MI_V1 = f"""Prompt version: extract_mi_v1

Extract medical-information (MI) request fields from the WHOLE message pack. Return every catalog field.

Field catalog:
{field_catalog_lines(MI_FIELDS)}

- mi.questions: the actual question(s) asked.
- mi.product: product the question is about.
- mi.topic: short topic label (dose, interaction, administration, storage, other) if stated.

Return JSON only:
{{
  "fields": [
    {{
      "field": "mi.questions",
      "value": "{NOT_STATED}",
      "confidence": 0.0,
      "source_ref": "email:MESSAGE_ID",
      "quote": ""
    }}
  ]
}}

Rules:
- One object per catalog field.
- Missing facts MUST be "{NOT_STATED}" with confidence 0.0 and an empty quote.
- {UNKNOWN_OVER_GUESSING}

Message pack:
{{pack}}
"""

UNDERSTAND_V1 = f"""Prompt version: understand_v1

Write a reviewer summary of this mailbox message and its PDFs.

Return JSON only:
{{
  "summary": "10 to 15 sentences",
  "relevant": true,
  "relevance_reason": "one line",
  "needs_human_review": false,
  "review_reasons": []
}}

Rules:
- summary is 10–15 sentences covering sender intent, what the attachments add, and whether this looks
  like a safety report, quality complaint, product question, or none of those — and why.
- relevant is true if the message is plausibly ICSR, PQC, or MI.
- needs_human_review is true when OCR is weak, handwriting is present, language is mixed, evidence
  conflicts, or you had to leave important facts unknown.
- Do not invent facts. If something is unclear, say so in the summary.
- {UNKNOWN_OVER_GUESSING}

Message pack:
{{pack}}
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

LITERATURE_SCREEN_V1 = f"""Prompt version: {PROMPT_LITERATURE}

This uploaded PDF is being screened as literature (not a Gmail safety mailbox item).
All content is SYNTHETIC / fictional. There are no real patients.

Question: does this document describe one or more identifiable patient cases?

An identifiable patient case means a narrative about a specific person who took a product
and had an adverse event (age/sex/initials, a reaction, a named product — even loosely).
A methods paper, review, or animal study with no person-level story is not identifiable.

If multiple distinct patients are described, list each as a separate case. Do not merge them.

Return JSON only:
{{
  "identifiable_patient_case": true,
  "case_count": 1,
  "rationale": "one or two sentences",
  "cases": [
    {{
      "index": 1,
      "summary": "one-line case summary",
      "excerpt": "verbatim span from the pack that identifies this case",
      "source_ref": "pdf:ATTACHMENT_ID:page:1"
    }}
  ]
}}

Rules:
- identifiable_patient_case is true only when at least one person-level case exists.
- case_count must equal the length of cases. Use 0 and [] when none exist.
- excerpt must be copied from the cited source_ref. Do not invent.
- source_ref must be one of the refs in the pack.
- {UNKNOWN_OVER_GUESSING}

Message pack:
{{pack}}
"""

PROMPT_TEMPLATES = {
    "understand_v1": UNDERSTAND_V1,
    "classify_v1": CLASSIFY_V1,
    "extract_icsr_v1": EXTRACT_ICSR_V1,
    "extract_pqc_v1": EXTRACT_PQC_V1,
    "extract_mi_v1": EXTRACT_MI_V1,
    PROMPT_LITERATURE: LITERATURE_SCREEN_V1,
}
