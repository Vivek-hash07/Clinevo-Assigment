# Smart Inbox Assistant — write-up

Clinevo live assignment: Forward Deployment / GenAI Integration Engineer.  
Prototype: Angular reviewer UI + FastAPI document pipeline + Neon Postgres.

This note explains the architecture, the stack deviations, how prompting works, what is limited, and what I would change for production. All mailbox and PDF examples are synthetic.

## 1. What the system does

A healthcare mailbox receives unstructured email and PDFs. A human currently reads every item, decides whether it is a safety report (ICSR), a quality complaint (PQC), a medical-information question (MI), or not relevant, then copies facts by hand.

The prototype automates the first pass:

1. Ingest a message (synthetic sample, uploaded PDF, or optional IMAP).
2. Detect PDF flavor and acquire text (digital extract, OCR / vision, translation).
3. Classify the **whole message** as multi-label ICSR / PQC / MI / Not Relevant.
4. Extract a fixed field catalog with confidence and a citation (`email:{id}` or `pdf:{id}:page:{n}`).
5. Hand a reviewer an editable workspace: accept, override with a reason, complete the case.

Missing facts are `"Not stated"`. The model is instructed never to invent names, doses, lots, dates, or outcomes.

## 2. Architecture

```text
                    Angular (localhost:8000 or Vercel)
                    sign-in · queue · PDF viewer · review
                                      │  HTTPS + cookies
                                      ▼
                    FastAPI (localhost:8080 or Render)
                    REST  ·  in-process worker pool
                                      │
           ┌──────────────────────────┼──────────────────────────┐
           ▼                          ▼                          ▼
    Neon Postgres              OpenRouter                   Optional mail
    messages, pdf_pages        gpt-4o-mini                  SMTP copy
    classifications            text + vision                IMAP read
    extracted_fields
    reviews, audit_events
    pipeline_runs, queue_jobs
```

Pipeline stages (each is a row in `queue_jobs`):

```text
mail/sync → mail/sync.mailbox → email/received
        ↘ pdf/attached → pdf/extracted ↘
          email/ingested → ai/understand → message/ready
                         → ai/classify → message/classified
                         → ai/extract  → literature/screen (articles / uploads)
```

Idempotency keys are Gmail/IMAP message id, or fixture key, plus attachment checksum. Re-clicks do not duplicate in-flight work. Each stage records `started_at`, `finished_at`, `duration_ms`, model, and prompt version.

## 3. Tech choices

The assignment suggests Angular → Spring Boot → Python AI → Oracle. Angular is kept. The rest is a documented deviation.

**Why one Python API instead of Spring Boot + Python.** The product work in seven days is PDF flavor detection, OCR, tables, vision, structured extraction, and a job queue. Those libraries are Python-native. A Java BFF would have been a second deploy, a second auth layer, and little extra product. A production Clinevo stack can still put Spring Boot in front later; the FastAPI service is already a clean AI/OCR worker.

**Why Postgres instead of Oracle.** Neon was available on day one. The schema is ordinary relational tables (`users`, `messages`, `attachments`, `pdf_pages`, `classifications`, `extracted_fields`, `reviews`, `audit_events`, `pipeline_runs`, `queue_jobs`). Mapping to Oracle later is a dialect change, not a redesign.

**Why an in-process queue instead of a cloud queue.** The assignment allows “a simple queue (even an in-process one)”. Jobs live in Postgres and are claimed with `FOR UPDATE SKIP LOCKED`. The FastAPI process starts a small worker pool on boot. That is enough to overlap OCR and LLM calls, retry, and show stage/status/duration in the UI without a second vendor.

**Why OpenRouter (`openai/gpt-4o-mini`).** One API for classification, extraction, translation, and vision-assisted OCR. Structured JSON schemas are enforced in `backend/app/ai_contracts.py`. Cost and latency fit a 15-document batch. A self-hosted model would have needed GPU time this assignment does not have.

**Why Load sample emails instead of live Gmail for the demo.** The assignment requires made-up test data (section 6). **Load sample emails** injects that catalog and runs the same ingest → PDF → classify → extract path a mailbox would. **Send sample email** and Gmail OAuth sync are wired for a verified Cloud app. The hosted OAuth client (`clinevo-api.onrender.com`) is still in Google Testing, so Google currently shows Error 403: access_denied (“has not completed the Google verification process”). That is the expected gate for an unverified / restricted-scope app — not a missing feature. Email/password sign-in plus Load sample emails is the complete walkthrough. IMAP remains an optional live-mail fallback that does not wait on Google verification.

## 4. Prompting approach

Prompts are versioned strings in `backend/app/prompts.py` (`classify_v1`, `extract_icsr_v1`, `extract_pqc_v1`, `extract_mi_v1`, `understand_v1`, `literature_screen_v1`, `pdf_step1_v1`).

Rules that appear on every call:

- Prefer unknown over guessing. If a fact is not in the pack, value is `"Not stated"`, confidence is `0.0`, quote is empty.
- Return JSON only. Schemas reject extra keys.
- Cite `source_ref` exactly as given in the pack.
- Quotes must be verbatim spans.

Classification is multi-label: the model returns `applies` for all four buckets independently, with a one-line reason. If any of ICSR / PQC / MI applies, Not Relevant must be false.

Extraction always returns the **full catalog** for the categories that apply, including empty fields. ICSR includes patient, reporter, product, reaction, seriousness, and a short narrative. PQC includes product, batch/lot, defect, photo mentioned. MI includes the question(s), product, and topic.

PDF step 1 is separate from scoring. Digital pages go through `pdfplumber`; weak or image-only pages are rasterized. Tesseract is a prior; the vision model is ground truth when the text layer is thin. Language is detected; non-English original text is kept; English is the working copy for step 2.

A cheap overlap check (`llm_hallucination_overlap_min`) flags extracted quotes that do not appear in the pack so the reviewer sees `needs_human_review`.

## 5. Human review and audit

The Angular queue lists category, confidence, summary, duration, PDF count, and skipped non-PDFs. The case screen shows:

- Email body and PDF viewer with page text, language, OCR confidence, tables, and image notes
- Classification reasons
- Editable fields with confidence and a **Highlight email / Highlight PDF page** control
- Accept, override (reason required), complete
- Timestamped `audit_events` and `pipeline_runs`

Accepted or overridden fields are locked. Later AI re-runs do not silently overwrite a human decision.

## 6. Test data

The catalog in `docs/samples/` exceeds the required counts: 14 reaction emails, 14 digital PDFs, 2 scan/handwriting-style PDFs, 5 articles, 2 non-English PDFs, 3 PQC-only, 2 MI-only, 2 irrelevant. The demo batch is 15 documents. A thin fatal case exists specifically so the model must leave most ICSR fields `"Not stated"`. A cracked-vial-plus-rash case exists so ICSR and PQC can both apply.

## 7. Literature screening (bonus)

**Upload PDF** on the queue bypasses mail. The same classify/extract pipeline runs. If the document looks like an article (or the reviewer asks), the model answers “identifiable patient case?” and lists cases. The reviewer can split a multi-case letter into separate queue items. `fictional-article-two-cases.pdf` is the walkthrough example.

## 8. Data handling

No real patient data is used. OpenRouter still sees the synthetic text. In production that is a DLP / BAA / VPC decision: either a contracted private endpoint, or on-prem models, plus redaction before any cloud call. Tokens and IMAP app passwords are encrypted at rest with `TOKEN_ENCRYPTION_KEY`. Secrets stay in environment variables.

## 9. Scope for this prototype vs production Gmail

- **Load sample emails** is the designed demo. It matches the assignment’s synthetic-data requirement and exercises the full pipeline.
- **Send sample email** and Gmail OAuth sync wait on Google’s verification of `clinevo-api.onrender.com`. While the OAuth app is in Testing, Google shows Error 403: access_denied (“has not completed the Google verification process”). That verification is the production follow-up, including the restricted `gmail.readonly` scope.
- IMAP with an app password is available if a reviewer wants a live inbox without that Google review.
- The 10–15 sentence summary is per **message**, not per PDF file. That matches whole-message classification.
- Scanned/handwritten PDFs in the catalog are generated image-only PDFs, not photographs of paper forms.
- `gpt-4o-mini` is a cost/latency choice. A larger model would improve handwriting and long articles.
- Render free-tier APIs sleep; the first request after idle can be slow.
- Extracted JSON for submission must be exported from a live run (`python -m app.scripts.batch_run --export`).

## 10. What I would change for production

- Put a Java/Spring BFF in front if that is the house standard; keep Python as the AI/OCR worker.
- Move the queue to a dedicated worker service (or Inngest) with a dashboard.
- Oracle or the customer’s mandated DB, with the same tables.
- Google OAuth verification (or a customer-managed mailbox connector) if live mail is required.
- DLP, VPC, audit export to the customer SIEM, and a human-review SLO.
- Prompt evals on a frozen synthetic gold set (the catalog in `docs/samples/source`).
- PDF virus scanning and attachment size quotas at the edge.

The prototype is meant to be run live in 15–20 minutes: load samples, open a dual-label case, show a `"Not stated"` field, override one value, show the audit row, then upload and split a two-case article.
