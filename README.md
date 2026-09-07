# Smart Inbox Assistant

Clinevo reviewer app: Angular on port 8000, FastAPI on port 8080, Neon Postgres from `backend/.env`.

Run Python locally. There is no Docker image for this project.

## Layout

```text
frontend   Angular reviewer UI
backend    FastAPI (reads backend/.env)
```

| Service | URL |
|---|---|
| Angular | http://localhost:8000 |
| FastAPI | http://localhost:8080 |
| Health | http://localhost:8080/api/health |
| After login | http://localhost:8000/inbox |

Open the app at **http://localhost:8000**, not `127.0.0.1`.

## Environment

The API reads a repo-root `.env` when present and then **`backend/.env`** (backend values take
precedence). Copy `backend/.env.example` if you need a fresh file. **Never commit either `.env`.**

Required: `DATABASE_URL`, `JWT_SECRET`, `TOKEN_ENCRYPTION_KEY`. SMTP values match Amazon Mail Manager (region `ap-south-1`).

## Google Cloud — any Google account can sign in

Continue with Google only asks for **openid, email, profile**. That is enough for any Google account once the consent screen is **published**.

1. Google Cloud → **APIs & Services** → **OAuth consent screen**
2. User type **External**
3. Click **Publish app** (status **In production**). Confirm the warning. You do **not** need Google’s brand verification for sign-in.
4. Keep the same Web client origins and redirect URI below.

If status stays **Testing**, Google will only allow emails you add as testers. Publishing is what opens it to every Google account.

**Gmail mailbox sync via OAuth** uses the restricted `gmail.readonly` scope. Google blocks that for unverified apps. Sign-in does not wait on that. After login, connect **IMAP + a Gmail app password** (recommended) or try **Connect Gmail OAuth** if your Cloud project already has test users. Tokens and app passwords are encrypted at rest. An in-process worker on FastAPI polls the mailbox every two minutes.

**Authorized JavaScript origins** (this is the origin)

```text
http://localhost:8000
```

**Authorized redirect URIs** (this is the callback / fallback)

```text
http://localhost:8080/api/auth/google/callback
```

Paste the client ID and secret into `backend/.env`:

```env
GOOGLE_CLIENT_ID=....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=....
GOOGLE_REDIRECT_URI=http://localhost:8080/api/auth/google/callback
```

Restart FastAPI after saving.

## Run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --reload-dir app --port 8080 --host 0.0.0.0
```

```bash
cd frontend
npm install
npm start
```

Tables are created on API startup.

## Mail intake (assignment path)

The assignment asks for **synthetic / dummy emails** (Day 6), not a live Gmail sync. That is the default:

1. Sign in.
2. Optionally tick **Also send a copy via SMTP** (Amazon Mail Manager from `smtp-credentials.csv` → Render `SMTP_*`).
3. Click **Load sample emails**. The Day 6 batch (ICSR, PQC, MI, articles, scans, non-English) lands in the reviewer queue and the AI pipeline runs.
4. SMTP, if checked, emails the same dummy messages to **your** address. The app does **not** read them back.

| Path | When to use | UI |
|---|---|---|
| **Load sample emails** | Required demo / Day 6 batch | Inbox → Load sample emails |
| **SMTP copy** | Optional proof that outbound mail works | Tick “Also send a copy” |
| **Upload PDF** | Literature bonus | Inbox → Upload PDF |
| **Advanced mail** | Optional live IMAP / Gmail | Inbox → Advanced mail |

### IMAP (recommended mailbox path)

Google’s Gmail API scope is restricted. IMAP is the production-ready workaround for a 7-day prototype:

1. Google Account → **Security** → turn on **2-Step Verification**.
2. Search **App passwords** → create one named `Clinevo`.
3. In the app, enter the Gmail address and the 16-character password (spaces are stripped).
4. Host defaults to `imap.gmail.com:993`, folder `INBOX`.
5. **Test connection**, then **Connect IMAP**. The first sync is queued automatically.

The app password is encrypted with `TOKEN_ENCRYPTION_KEY` (Fernet) and is only used to read mail.

Works with Outlook / Yahoo / Fastmail too — set the IMAP host if it is not Gmail.

### Gmail OAuth (optional)

Enable the **Gmail API** on the same Google Cloud project as the OAuth client. After sign-in, **Connect Gmail OAuth** requests `gmail.readonly`. Google will refuse unverified apps except listed test users.

### In-process queue (no Inngest)

FastAPI starts a worker thread pool on boot. Jobs live in Postgres (`queue_jobs`). The inbox **pipeline strip** shows stage, status, duration, and the last error.

What runs:

1. `mail/sync` — every 2 minutes (and on **Sync my mail**), one job per connected mailbox.
2. `mail/sync.mailbox` — Gmail History API or IMAP UID cursor; enqueues each new message id.
3. `email/received` — fetch sender, subject, date, body, PDF bytes; log non-PDFs; upsert by `(user_id, provider_message_id)`.
4. `pdf/attached` — flavor, digital extract or OCR/vision, language + translation, `pdf_pages`.
5. `ai/understand` → `ai/classify` → `ai/extract` → optional `literature/screen`.

Manual **Sync my mail** posts `POST /api/mail/sync`. Re-runs are idempotent while a job is still queued or running.

### Synthetic test mail

Only made-up content. From the inbox, **Send sample mail** (needs SMTP + a connected mailbox), or skip mail and **Load local fixtures**.

```bash
cd backend
source .venv/bin/activate
python -m app.scripts.seed_mailbox you@gmail.com
```

Wait ~15 seconds for the mailbox to accept the messages, then sync. One sample includes a CSV so you can confirm non-PDFs are logged and skipped.

### Reviewer queue API

`GET /api/messages?status=pending|processing|ready|reviewed`

Statuses: **pending** (ingested, PDFs extracted), **processing** (pipeline running), **ready** (AI finished — Day 4), **reviewed** (human signed off — Day 5). `GET /api/messages/{id}` returns body and attachment metadata. `GET /api/messages/{id}/attachments/{attachmentId}/pages` returns per-page original text, translation, flavor, OCR confidence, LLM score, and `pdf:{id}:page:{n}` source refs.

## PDF step 1 (Day 3)

After `email/received` or **Upload PDF** stores a file, the worker runs **`pdf/attached`** (one job per attachment, idempotent on message id + checksum).

1. **Flavor detector** — local signals (text-layer density, images, columns) plus OpenRouter confirmation.
2. **Digital pages** — `pdfplumber` text (column-aware for articles) and real table grids. OpenRouter cleans, scores, and repairs tables if the local grid is empty or ragged.
3. **Scanned / handwriting** — rasterize with pypdfium2 → Tesseract OCR (if installed) → OpenRouter vision on the page image. OCR is a prior; vision is ground truth when the layer is weak. Both scores are stored.
4. **Language** — `langdetect` + OpenRouter. Non-English pages are translated to English; **original text is always kept**. The working `text` field is English so Day 4 can classify on one language.
5. **Per-page rows** in `pdf_pages` so later facts can cite `pdf:{attachmentId}:page:{n}`.

Set `OPENROUTER_API_KEY` in `backend/.env`. Optional but recommended for scan confidence:

```bash
brew install tesseract
```

Without Tesseract, scanned pages still go through OpenRouter vision. Without an API key, local extract still runs and the page is flagged `needs_human_review`.

## Auth

- `/sign-up` and `/sign-in` — email/password or Continue with Google
- `/forgot-password` — SMTP reset email with a random, hashed, 30-minute token
- `/reset-password` — one-time link; requesting another link invalidates earlier links
- Access cookies are signed and short lived; refresh tokens are hashed, rotated, and revocable
- Password reset revokes all previous sessions
- After login you land on `/inbox`

## Day 6 — synthetic fixtures and batch run

All mailbox and PDF samples are **made-up**. There is no real patient data.

| Required | Catalog |
|---|---|
| Emails with reaction detail | 14 |
| Digital PDFs | 14 |
| Scanned / handwritten PDFs | 2 |
| Fictional article PDFs | 5 |
| Non-English PDFs | 2 |
| PQC-only | 3 |
| MI-only | 2 |
| Irrelevant / marketing | 2 |

**Load 15 documents into the reviewer queue (no Gmail):**

1. Sign in at http://localhost:8000
2. Keep FastAPI on 8080 (the in-process worker starts with the API)
3. Click **Load local fixtures**

Or from the backend venv:

```bash
cd backend
source .venv/bin/activate
python -m app.scripts.batch_run --write-pdfs --load --user-email you@example.com --wait 900 --export
```

That writes:

- `artifacts/day6/pdfs/` — every synthetic PDF (upload these for the literature bonus)
- `artifacts/day6/extracted/*.json` — extracted JSON per document
- `artifacts/day6/timings.csv` and `timings.json` — `started_at` / `finished_at` / `duration_ms` rollup
- `artifacts/day6/coverage.json` — Day 6 required counts

Gmail path (optional): **Send sample mail** then **Sync my mail**, or `python -m app.scripts.seed_mailbox you@gmail.com`.

**Bonus — literature screening:** **Upload PDF** on the queue (article PDFs from `artifacts/day6/pdfs/`, especially `fictional-article-two-cases.pdf`). The same review UI asks **identifiable patient case?** and can **split** multiple cases. Each child reuses classify/extract.

For production, serve the Angular build and `/api` from the same HTTPS origin. Set
`APP_ENV=production`, HTTPS `FRONTEND_URL`/`BACKEND_URL`, and `COOKIE_SECURE=true`. The backend
refuses unsafe production settings.
