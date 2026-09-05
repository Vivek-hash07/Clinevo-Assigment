# Smart Inbox Assistant — Production Delivery Plan

Clinevo live assignment: **Forward Deployment / GenAI Integration Engineer**.  
Goal: a working app that reads incoming emails and PDF attachments, classifies them, extracts key facts, and hands a first pass to a human reviewer.

This plan is written so we can ship a **production-style prototype in 7 days**, defend every stack choice in the write-up, and run a 15–20 minute live walkthrough that looks like a real product.

---

## 1. What we are building

A **Smart Inbox Assistant** for a healthcare / patient-safety mailbox.

Flow:

1. Connect to a real **test Gmail mailbox**.
2. Ingest sender, subject, date, body, and **PDF attachments** (other file types are logged, not processed).
3. Understand each PDF (digital, scanned/handwritten, article, non-English).
4. Classify the **whole message** into one or more of four buckets.
5. Extract structured facts with **confidence** and **source citations**.
6. Show a reviewer queue where a human **accepts or overrides** the AI.

This is document understanding + classification + human-in-the-loop review — not a pharma-domain exam.

---

## 2. The four categories (multi-label)

A message can land in **more than one** bucket. Never force a single label.

| Category                    | Meaning                                     | Look for                                                                |
| --------------------------- | ------------------------------------------- | ----------------------------------------------------------------------- |
| **Safety Report (ICSR)**    | Patient had a bad reaction to a drug        | Patient + reporter + drug + bad outcome (even loosely)                  |
| **Quality Complaint (PQC)** | Something physically wrong with the product | Broken seal, wrong color, contamination, damaged packaging, counterfeit |
| **Info Request (MI)**       | Question about a product                    | Dosing, how to take it, interactions — no reaction, no defect           |
| **Not Relevant**            | Everything else                             | Marketing, spam, internal admin                                         |

---

## 3. Stack decisions (and how we defend them)

Assignment suggests Angular → Spring Boot → Python AI → Oracle. We **keep Angular**, replace Java with a single Python API, and document why.

| Layer        | Choice                                        | Reason                                                                                                                            |
| ------------ | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Frontend     | **Angular** on **Vercel**                     | Matches Clinevo production UI. Do not switch to React.                                                                            |
| Backend      | **FastAPI (Python)** on **Railway or Render** | OCR, PDF tables, OpenRouter, Inngest, Gmail are Python-native. One service instead of Spring Boot + Python for a 7-day prototype. |
| Jobs / queue | **Inngest**                                   | Observable pipelines, retries, per-document timing. Replaces “simple in-process queue”.                                           |
| Database     | **Postgres (Neon)**                           | Already available. Schema designed so it could move to Oracle. Document the swap.                                                 |
| Auth + mail  | **One Google OAuth client**                   | Sign-in and Gmail read in one consent.                                                                                            |
| AI           | **OpenRouter**                                | Email understanding, classification, extraction, translation, summaries, vision OCR assist.                                       |
| PDF step 1   | **pdfplumber / pypdf + OCR / vision**         | Digital text vs scanned pages.                                                                                                    |
| PDF step 2   | **OpenRouter structured JSON**                | Scoring, classification, fact extraction. Never invent fields.                                                                    |

**Do not host FastAPI on Vercel.** OCR + LLM can take 30–90 seconds. Vercel serverless will time out. Vercel = Angular only.

**Oracle:** skip for the prototype unless an instance already exists. Write-up line: _Oracle in production; Postgres here for speed; tables map 1:1._

---

## 4. Architecture

```text
Gmail (test mailbox)
        │  Inngest cron / gmail.sync
        ▼
 FastAPI  ── Inngest functions ─────────────────────────────┐
   │         1. ingest-email                                 │
   │         2. process-attachment                           │
   │              ├─ digital: pdfplumber / pypdf             │
   │              └─ scan/handwriting: OCR / vision LLM      │
   │         3. understand-document (OpenRouter)             │
   │         4. classify-message (multi-label + reasons)     │
   │         5. extract-facts (ICSR / PQC / MI)              │
   │         6. persist + audit                              │
   │                                                         │
   ▼                                                         ▼
 Neon Postgres (messages, pdfs, facts, reviews, audit_log)
        ▲
 Angular reviewer UI (queue, PDF viewer, editable fields, accept/override)
        │
 Google OAuth (openid + email + gmail.readonly)
```

Repo layout (target):

```text
frontend          # Angular reviewer UI (local :8000)
backend           # FastAPI + Inngest serve (local :8080)
backend/app/prompts.py  # classify / extract prompt templates
```

---

## 5. Google OAuth — origins and redirect URIs

Create **OAuth 2.0 Client ID → Web application**. Enable **Gmail API**. App in **Testing**; add the test Gmail as a test user (Gmail scopes are restricted; no Google verification in 7 days).

Use **one backend authorization-code flow**. Angular never holds the client secret. User clicks Sign in → FastAPI starts OAuth → Google redirects to FastAPI → store refresh token → Angular gets our JWT.

Request `access_type=offline` and `prompt=consent` once so background Inngest sync keeps working after the tab is closed.

### Scopes (login + mail in one consent)

```text
openid
email
profile
https://www.googleapis.com/auth/gmail.readonly
```

### Local

**Authorized JavaScript origins**

```text
http://localhost:8000
```

**Authorized redirect URIs (callback / fallback)**

```text
http://localhost:8080/api/auth/google/callback
```

- Angular (`frontend`): **[http://localhost:8000](http://localhost:8000)**
- FastAPI (`backend`): **[http://localhost:8080](http://localhost:8080)**
- After login the app lands on **[http://localhost:8000/inbox](http://localhost:8000/inbox)**
- No trailing slashes
- Env: `GOOGLE_REDIRECT_URI=http://localhost:8080/api/auth/google/callback`
- Use `localhost`, not `127.0.0.1`, so cookies and Google origins match

### Production (Vercel frontend + hosted FastAPI)

Replace with real hosts. Examples:

**Authorized JavaScript origins**

```text
https://your-app.vercel.app
https://your-api.up.railway.app
```

**Authorized redirect URIs**

```text
https://your-api.up.railway.app/api/auth/google/callback
```

Do **not** put a Vercel URL in redirect URIs unless the callback actually runs on Vercel. The callback is Python, so it belongs on Railway / Render / Fly / Cloud Run.

Add `www` and non-`www` if both are used. Preview Vercel URLs only if we will log in from those previews; otherwise production + localhost is enough.

---

## 6. Hosting map

| Piece                   | Where                         | Why                            |
| ----------------------- | ----------------------------- | ------------------------------ |
| Angular                 | Vercel                        | Static SPA, previews, fast.    |
| FastAPI + Inngest serve | Railway or Render (Docker)    | Long jobs, one service.        |
| Inngest Cloud           | Inngest                       | Dashboard for the walkthrough. |
| Postgres                | Neon                          | Already in the project.        |
| Secrets                 | Host env vars                 | Never commit `.env`.           |
| Google OAuth            | Same GCP project as Gmail API | One client ID.                 |

Local Inngest: `INNGEST_DEV=1` + Inngest Dev Server.  
Production: `INNGEST_EVENT_KEY` + `INNGEST_SIGNING_KEY`. Serve at `https://<api>/api/inngest`.

---

## 7. Inngest pipelines

Name functions so the Inngest dashboard tells the whole story in the live demo.

| Function        | Trigger                             | Visible steps                                                      |
| --------------- | ----------------------------------- | ------------------------------------------------------------------ |
| `gmail/sync`    | Cron every 1–2 min                  | List unread → enqueue each message id (idempotent)                 |
| `email/ingest`  | `email/received`                    | Fetch metadata + body + attachments → save raw → fan-out PDFs      |
| `pdf/process`   | `pdf/attached`                      | Detect flavor → OCR or text extract → tables/images → language     |
| `ai/understand` | `pdf/extracted` or `email/ingested` | OpenRouter: summary, relevance                                     |
| `ai/classify`   | `message/ready`                     | Multi-label + confidence + one-line reason each                    |
| `ai/extract`    | `message/classified`                | ICSR / PQC / MI fields; `"Not stated"` if missing; source pointers |
| `audit/write`   | every step                          | Input hash, model, prompt version, latency_ms, token usage         |

**Idempotency key:** Gmail `messageId` + attachment checksum. Re-runs must not duplicate rows.

**Required metric:** `started_at`, `finished_at`, `duration_ms` per document. Process **10–15 samples automatically** and report timings.

---

## 8. PDF pipeline — two steps so we do not miss content

### Step 1 — Acquire text (OCR / extract)

1. Detect flavor: text-layer density, image-only pages, columns, language.
2. Branch:

- **Digital:** `pdfplumber` / `pypdf` (keep labels and form fields aligned).
- **Scanned / handwriting:** Tesseract and/or OpenRouter vision with page images. Keep **OCR confidence**.
- **Article:** column-aware extract; isolate case narrative vs references.
- **Non-English:** detect language; translate to English; **keep original** + translation.

1. Tables → real rows/columns JSON, not flattened strings.
2. Meaningful images (damaged product, rash, filled checkbox form) → short caption + `needs_human_review=true`.

### Step 2 — LLM score and extract (OpenRouter)

Same structured schema every time:

- `classifications[]`: `{ category, confidence, reason }`
- `summary`: 10–15 sentences; relevant or not, and why
- `fields[]`: `{ name, value, confidence, source_type, source_ref }`
- `source_ref` = `email:{id}` or `pdf:{id}:page:{n}` (required for audit)
- Missing facts = `"Not stated"` — never invent

Classify on the **whole message** (email body + all PDFs), not per file in isolation. A reaction in a PDF and a question in the email can be **ICSR + MI**.

---

## 9. Extraction contracts

### Safety Report (ICSR)

| Group     | Examples                                       |
| --------- | ---------------------------------------------- |
| Patient   | Age, sex, weight/height, relevant history      |
| Reporter  | Who reported, role, country                    |
| Product   | Name, dose, route, start/stop dates            |
| Reaction  | What happened, when it started, outcome        |
| Severity  | Death, hospitalization, life-threatening, etc. |
| Narrative | Short AI-written case summary                  |

### Quality Complaint (PQC)

Product / batch / lot, what’s wrong, whether a photo was mentioned.

### Info Request (MI)

The actual question(s) and the product / topic.

### Field shape (every extracted fact)

```json
{
  "field": "patient.age",
  "value": "Not stated",
  "confidence": 0.0,
  "source": { "type": "email", "id": "...", "quote": "..." }
}
```

Reviewer override stores `old_value`, `new_value`, `user_id`, `at`.  
AI never silently overwrites an accepted review.

---

## 10. Data model (minimum tables)

- `users` — Google identity
- `gmail_credentials` — refresh token (encrypted)
- `messages` — sender, subject, date, body, status
- `attachments` — filename, mime, checksum, processed flag
- `pdf_pages` — page number, text, language, ocr_confidence, flavor
- `classifications` — category, confidence, reason
- `extracted_fields` — field, value, confidence, source
- `reviews` — accept / override
- `audit_events` — every AI decision + every reviewer action
- `pipeline_runs` — Inngest run id, timings, model, prompt version

Ground rules:

- Say **unknown / Not stated** instead of guessing.
- Log everything. Timestamp reviewer actions.
- **No real patient data — ever.** Synthetic only.
- If using a cloud AI API, note the data-handling trade-off in the write-up.

---

## 11. Day-by-day roadmap (7 days)

### Day 0–1 — Foundation

1. Scaffold `frontend` (Angular) and `backend` (FastAPI). Prompts live in `backend/app/prompts.py`.
2. Local: Angular `:8000`, FastAPI `:8080`, Inngest Dev Server later, Neon.
3. Create tables listed in section 10.
4. Google OAuth login working end-to-end (before Gmail sync).
5. Health endpoint + README env placeholders. **Never commit** `.env`**.** Rotate any key that was ever in git.

### Day 2 — Mail intake

1. After OAuth, store Gmail refresh token encrypted.
2. `gmail/sync` via Inngest: sender, subject, date, body, PDF attachments; log non-PDFs.
3. Send synthetic test emails to the mailbox.
4. Reviewer queue API: `pending / processing / ready / reviewed`.

### Day 3 — PDF step 1

1. Flavor detector + digital extract + table extract fallback use LLM via Openrouter for all step 1.
2. Scan path: rasterize pages → OCR / vision → confidence.
3. Language detect + translate; keep original.
4. Store per-page text so facts can cite page numbers.

### Day 4 — OpenRouter step 2 (25% of score)

1. Versioned prompts (`classify_v1`, `extract_icsr_v1`, …).
2. JSON schema / structured output only.
3. Multi-label classification + reasons.
4. ICSR / PQC / MI extraction with `"Not stated"`.
5. Prompt rule in every call: _unknown over guessing_.

### Day 5 — Angular reviewer UI (the live demo)

- Queue: category chips, confidence, summary, duration.
- Detail: email body + PDF viewer + AI summary.
- Editable fields with confidence and **source** link (highlight page / email).
- Accept / override + required override reason.
- Timestamped actions in `audit_events`.
- Empty, error, and processing states.

### Day 6 — Fixtures, batch run, bonus

Create **only synthetic** data:

| Required                             | Count |
| ------------------------------------ | ----- |
| Emails with reaction detail (varied) | ≥ 10  |
| Digital PDFs                         | ≥ 5   |
| Scanned / handwritten PDFs           | ≥ 2   |
| Fictional article PDFs               | ≥ 5   |
| Non-English PDFs                     | ≥ 2   |
| PQC-only                             | ≥ 2   |
| MI-only                              | ≥ 2   |
| Irrelevant / marketing               | ≥ 1   |

Run the full Inngest pipeline on **10–15 documents**. Export:

- extracted JSON per document
- timing table
- screenshots / 60–90s screen recording

**Bonus (+30%):** upload article PDFs outside Gmail → same UI → “identifiable patient case?” → split multiple cases. Reuse classify/extract. Do this only if Day 5 UI already works.

### Day 7 — Deploy and submit

1. Angular → Vercel; FastAPI → Railway/Render; Inngest Cloud → `https://<api>/api/inngest`.
2. Update Google origins / redirects; test login + Gmail on the live URL.
3. README: local run, env placeholders, architecture, how to seed fixtures.
4. Write-up (2–5 pages): diagram, Python-instead-of-Java, OpenRouter vs self-host, Postgres vs Oracle, prompts, limitations, production next steps (DLP, VPC, Oracle, Java BFF).
5. Email repo + live URL + sample outputs to:

- [pavithra.r@clinevotech.com](mailto:pavithra.r@clinevotech.com)
- [vivek.w@clinevotech.com](mailto:vivek.w@clinevotech.com)
- [ashish.b@clinevotech.com](mailto:ashish.b@clinevotech.com)
- [rehan.n@clinevotech.com](mailto:rehan.n@clinevotech.com)

---

## 12. Scoring reminder (build first)

| Area                         | Weight |
| ---------------------------- | ------ |
| Core functionality           | 30%    |
| AI / LLM quality             | 25%    |
| Code & architecture          | 20%    |
| Domain (4 categories)        | 10%    |
| Traceability & data handling | 10%    |
| Documentation                | 5%     |
| Bonus literature screening   | +30%   |

A working prototype with rough edges beats a polished document with nothing running.

---

## 13. Walkthrough script (15–20 min)

1. Open live app → Google sign-in → Gmail connected.
2. Show Inngest: `gmail/sync` → `pdf/process` (OCR vs digital) → `ai/extract`.
3. Open a scanned PDF: OCR confidence + page cite.
4. Open a dual-label case (defect + reaction).
5. Override a field → audit row appears.
6. Show a `"Not stated"` field we refused to invent.
7. Show the timing table for the 10–15 batch.
8. One sentence: _Python because OCR/LLM/Gmail are the product; Angular because that’s their reviewer surface; Inngest because they asked for a queue and we made it observable._

---

## 14. Immediate next actions

1. Google Cloud: create Web client, paste **local** origins/URIs, fill `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.
2. Scaffold Angular `:8000` (`frontend`) + FastAPI `:8080` (`backend`). Inngest is Day 2.
3. Confirm OAuth callback returns a user **before** touching PDFs.

---

## 15. Non-negotiables

- Synthetic / made-up data only. No real patients, ever.
- `"Not stated"` instead of guessing.
- Every fact links to email or PDF page.
- Every AI decision and reviewer action is logged.
- Secrets stay in env vars, not git.
- Angular frontend; Python backend; Inngest for pipelines; OpenRouter for LLM; Google for auth + mail.
