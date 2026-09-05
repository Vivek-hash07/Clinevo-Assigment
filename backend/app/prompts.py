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
