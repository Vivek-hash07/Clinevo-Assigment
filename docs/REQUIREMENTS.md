# Assignment requirements vs this prototype

Compared against **Clinevo Live Project Assignment — Smart Inbox Assistant** (`Clinevo_Assignment.pdf`).

Legend: **Met** · **Met with a documented deviation** · **Met via synthetic load** (live Gmail after Google verification)

## Section 3A — Read the mail

| Requirement | Status | Notes |
|---|---|---|
| Accept incoming messages; connect a real test mailbox | **Met via synthetic load** | The assignment also requires made-up test data. **Load sample emails** is the demo path and runs the full pipeline. Live **Send sample email** / Gmail OAuth wait on Google verification of `clinevo-api.onrender.com` (Testing app → Error 403: access_denied). IMAP is an optional fallback that does not need that verification. |
| Sender, subject, date, body | **Met** | Stored on `messages` and shown on the queue and review screens. |
| Grab every PDF; log other file types | **Met** | PDFs are processed. Non-PDFs (e.g. a CSV in the catalog) are stored as skipped with a reason. |
| Save results in a queryable store (Oracle suggested) | **Met with deviation** | Neon Postgres. Tables map 1:1 to what Oracle would hold. Explained in the write-up. |

## Section 3B — Understand the PDFs

| Requirement | Status | Notes |
|---|---|---|
| Detect PDF flavor (digital / scanned / handwritten / article / non-English) | **Met** | Local signals + OpenRouter confirmation. Non-English is a language path, not a separate flavor enum. |
| Digital text extract, keep labels aligned | **Met** | `pdfplumber` / `pypdfium2`, then LLM cleanup. |
| Scanned / handwritten: OCR or vision + confidence | **Met** | Rasterize → Tesseract if installed → OpenRouter vision. OCR confidence stored. |
| Articles: multi-column, isolate case vs references | **Met** | Column-aware extract + literature screening on article flavor / upload. |
| Non-English: detect, translate, keep original | **Met** | Spanish and French samples. Original page text is stored; English is the working text. |
| Tables as real rows/columns | **Met** | Local grid + LLM repair. Shown on the review PDF panel when present. |
| Meaningful images: short caption + flag for review | **Met** | `image_notes` on `pdf_pages`, shown on the review screen. |
| 10–15 sentence summary, relevant or not, and why | **Met with assumption** | Summary is written for the **whole message** (email + all PDFs), which matches the “classify the whole message” rule. |

## Section 3C — Sort and score

| Requirement | Status | Notes |
|---|---|---|
| Multi-label into ICSR / PQC / MI / Not Relevant | **Met** | Independent applies flags. Dual-label sample: `icsr-dual-defect`. |
| Confidence + one-line reason each | **Met** | Shown as chips + reason list on the case screen. |
| Angular review queue with accept / override | **Met** | Queue + detail workspace. |

## Section 3D — Pull out key facts

| Requirement | Status | Notes |
|---|---|---|
| ICSR groups: patient, reporter, product, reaction, severity, narrative | **Met** | See `ICSR_FIELDS` in `backend/app/constants.py`. |
| `"Not stated"` instead of guessing | **Met** | Prompt rule + stored value. Sparse death sample: `icsr-fatal-thin`. |
| Every fact links to email or PDF page | **Met** | `source_ref` = `email:{id}` or `pdf:{id}:page:{n}`. Reviewer can highlight the quote. |
| PQC: product / batch / lot, defect, photo mentioned | **Met** | |
| MI: question(s) and product / topic | **Met** | |

## Section 3E — Ground rules

| Requirement | Status | Notes |
|---|---|---|
| Unknown over guessing + confidence per field | **Met** | |
| Log every AI decision and timestamp reviewer actions | **Met** | `audit_events`, `pipeline_runs`, `reviews`. |
| No real patient data | **Met** | Synthetic catalog only. |
| Cloud AI data-handling note | **Met** | Write-up. OpenRouter / the upstream model sees synthetic text only. |
| Process 10–15 documents and report duration | **Met** | Demo batch is 15. Export `artifacts/day6/timings.csv`. |

## Section 4 — Bonus literature screening

| Requirement | Status | Notes |
|---|---|---|
| Upload article PDFs outside the mailbox | **Met** | Inbox **Upload PDF**. |
| Identifiable patient case? | **Met** | Reviewer can confirm or override the AI. |
| Split multiple cases | **Met** | `fictional-article-two-cases.pdf` and the case series. |
| Reuse Section 3 UI | **Met** | Same queue and extract pipeline. |

## Section 5 — Suggested stack

| Suggested | This prototype | Why |
|---|---|---|
| Angular | Angular 19 | Matches Clinevo’s reviewer UI. |
| Spring Boot + Python AI | FastAPI (Python) only | OCR, PDF, Gmail/IMAP, OpenRouter, and the queue are Python-native. One service for a 7-day prototype. |
| Oracle | Neon Postgres | Available immediately; schema is relational and portable. |
| Simple in-process queue | Postgres `queue_jobs` + worker thread pool inside FastAPI | Observable stages, retries, idempotency. No extra Inngest Cloud dependency. |
| Any LLM | OpenRouter `openai/gpt-4o-mini` (text + vision) | Structured JSON, vision OCR assist, one API key. |

## Section 6 — Test data counts

All required counts are met or exceeded. See `docs/samples/catalog.json` and `docs/samples/README.md`.

## Section 7 — Deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Working prototype | Local README; hosted Angular + FastAPI if deployed |
| 2 | Source code | This git repo |
| 3 | README with setup + env placeholders | Root `README.md` |
| 4 | 2–5 page write-up | `docs/WRITEUP.md` |
| 5 | Sample outputs | `docs/samples/` + `artifacts/day6/` (export extracted JSON after a run) |
| 6 | Bonus | Literature upload / screen / split |

## Design choice: synthetic load now, live Gmail after Google verification

1. **Load sample emails** is the walkthrough. The assignment’s section 6 is synthetic data; the queue, PDF pipeline, classify, extract, and review all run from that button.
2. **Send sample email** and **Gmail OAuth sync** are implemented for a verified Cloud app. The hosted client (`clinevo-api.onrender.com`) is still in Google **Testing**, so Google shows:

   > Access blocked: clinevo-api.onrender.com has not completed the Google verification process  
   > Error 403: access_denied

   Completing that verification is a production step (restricted `gmail.readonly` scope). Until then, email/password sign-in + Load sample emails is the complete demo.
3. IMAP with an app password is available under Advanced mail if a reviewer wants a live inbox without Gmail API verification.
4. Suggested Java + Oracle layers were not built; the write-up defends Python + Postgres.
5. Before you email Clinevo: **export live extracted JSON**, **capture screenshots or a short recording**, and follow `docs/SUBMISSION.md`.
