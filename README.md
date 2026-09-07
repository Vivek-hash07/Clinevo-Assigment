# Smart Inbox Assistant

A working app that reads incoming mail and PDF attachments, figures out what each message is about, pulls out the important facts, and gives a human reviewer a first draft to check — instead of starting from a blank page.

Think of it as a **smart mailbox for patient-safety and product-quality mail**. A doctor, patient, or warehouse might send an email with a PDF. Today a person has to read every one by hand. This prototype does the first pass with AI, then a reviewer accepts or corrects the result.

Every example in this project is **made-up / synthetic**. There is no real patient data.

| | Address |
|---|---|
| Reviewer screen (on your laptop) | http://localhost:8000 |
| API (on your laptop) | http://localhost:8080 |
| Health check | http://localhost:8080/api/health |
| After you sign in | http://localhost:8000/inbox |
| Source code | https://github.com/Vivek-hash07/Clinevo-Assigment |
| Live reviewer screen | https://clienvo.vercel.app |
| Live API | https://clinevo-api.onrender.com |

Open the app at **http://localhost:8000** (use `localhost`, not `127.0.0.1`).

**Jump to:** [What you need](#what-you-need-before-you-start) · [Run locally](#run-it-on-your-laptop-step-by-step) · [IMAP + Sync](#how-to-connect-imap-and-sync-email-extra) · [Google is in Testing](#google-sign-in-and-gmail--testing-mode)

---

## In plain English: what happens

1. A message arrives — either from **Load sample emails**, from **Upload PDF**, or (optionally) from a real inbox via **IMAP** or **Gmail sync**.
2. The app reads the email body and every PDF. Other file types (for example a CSV) are logged and skipped.
3. It decides which of four buckets apply. A message can be in **more than one** bucket at once.
4. It fills in a form of facts (age, product, what went wrong, and so on). If something is not written in the source, it says **Not stated** instead of guessing.
5. A reviewer sees the email, the PDF, the AI summary, and the form. They can **accept**, **override** (with a reason), or **complete** the case. Every action is timestamped.

The four buckets:

| Name you will see | Everyday meaning |
|---|---|
| Safety Report (ICSR) | A person had a bad reaction to a product |
| Quality Complaint (PQC) | Something is physically wrong with the product (broken seal, wrong colour, …) |
| Info Request (MI) | Someone only has a question (dose, how to take it) — no reaction, no defect |
| Not Relevant | Marketing, spam, or anything else |

---

## How to try it (the walkthrough)

You do **not** need Gmail for the demo. The assignment asks for made-up test emails, and that is what this button uses.

1. Sign in with **email and password** (or Google, on your laptop).
2. Click **Load sample emails**. Fifteen synthetic cases appear in the queue.
3. Wait until a row says **Ready** (the strip at the top shows the work in progress).
4. Open a case. Check the classification, the extracted fields, and the highlighted source (email or PDF page).
5. Accept or override a field. Watch the audit trail.
6. Optionally **Upload PDF** (try `artifacts/day6/pdfs/fictional-article-two-cases.pdf`) and split two patient cases — that is the bonus.

---

## What the assignment asked for vs what we added

### Asked for — and built

| Asked for | What you see |
|---|---|
| Read mail: sender, subject, date, body | Queue and case screen |
| Process PDF attachments; log other files | PDFs extracted; skipped files listed |
| Four PDF “flavours”: digital, scanned/handwritten, article, non-English | Flavour, OCR confidence, translation (original kept) |
| Tables and a short note on meaningful images | Shown on the PDF panel |
| Sort into the four buckets, with confidence and a one-line reason | Chips + reason list |
| Extract ICSR / PQC / MI facts; never guess | Form fields; **Not stated** when missing |
| Every fact links back to the email or PDF page | **Highlight email / Highlight PDF page** |
| Angular review screen: accept or override | Case workspace |
| Log every AI and reviewer action | Audit trail |
| 10–15 made-up documents and how long each took | Sample catalog + timing export |
| Optional literature screening | **Upload PDF** → identifiable case? → split |

### Extra — not required, but implemented

These are beyond the written assignment. They are in the product so a real mailbox *can* be used later, and so a reviewer can sign in without Google.

| Extra | Where | Why it is there |
|---|---|---|
| **Load sample emails** (no inbox needed) | Main inbox button | Assignment data is synthetic. This is the reliable demo: same pipeline as real mail. |
| **IMAP connect** | Inbox → **Advanced mail** | Read a real Gmail / Outlook / Yahoo inbox with an **app password**, without Google’s Gmail API review. |
| **Sync email** | After IMAP (or Gmail) is connected | Pulls new messages into the same reviewer queue and runs the same AI steps. |
| **Gmail OAuth connect** | Advanced mail | One-click “connect my Gmail”. Ready for when Google finishes verifying `clinevo-api.onrender.com`. |
| **Send sample email** | Mail seed / SMTP path | Can post the same dummy emails into a live mailbox, then sync them back. Waits on Google verification on the hosted app (see below). |
| **Email + password accounts** | Sign in / Sign up | You can use the app without Google. |
| **Forgot / reset password** | Sign-in screen | Reset link by email if SMTP is configured. |
| **Each reviewer has their own queue** | After login | Your samples and mailbox stay on your account. |
| **Pipeline strip** | Top of the inbox | Shows stage (read PDF, classify, extract), status, and how long it took. |
| **Source highlighting** | Case screen | Click a field → the quote is marked in the email or on the PDF page. |
| **Override reason required** | Case screen | A human correction is always explained and locked so AI will not overwrite it later. |
| **Hosted demo** | Vercel + Render | Live URL for the walkthrough, not only a laptop. |

**IMAP + Sync** is the extra live-mail path that works *without* waiting on Google’s Gmail API verification: create a Gmail app password, paste it under Advanced mail, click **Connect**, then **Sync now**. New mail is read, PDFs are processed, and cases land in the same queue as **Load sample emails**.

---

## Flowchart — how a message moves

Start at the top. Everything ends in the same reviewer screen.

```mermaid
flowchart TD
  A[Reviewer signs in] --> B{How does mail arrive?}

  B -->|Demo: Load sample emails| C[15 made-up emails + PDFs<br/>go straight into the queue]
  B -->|Extra: IMAP connect + Sync| D[Read a real inbox with an app password]
  B -->|Extra: Gmail OAuth + Sync| E[Read Gmail after Google verification]
  B -->|Bonus: Upload PDF| F[Article PDF, no mailbox]

  D --> G[Fetch sender, subject, date, body, PDFs]
  E --> G
  C --> H[Save the message]
  G --> H
  F --> H

  H --> I[Understand each PDF]
  I --> I1[Digital: extract text]
  I --> I2[Scan / handwriting: OCR + vision]
  I --> I3[Article: columns + case vs references]
  I --> I4[Non-English: translate, keep original]
  I1 --> J
  I2 --> J
  I3 --> J
  I4 --> J

  J[AI summary of the whole message] --> K[Classify: ICSR / PQC / MI / Not relevant]
  K --> L[Extract facts with confidence and source]
  L --> M[Reviewer queue]
  M --> N[Open a case: email + PDF + form]
  N --> O{Human check}
  O -->|Accept| P[Lock the field]
  O -->|Override + reason| Q[Save old value, new value, who, when]
  O -->|Complete| R[Case marked Reviewed]
  P --> R
  Q --> R
```

Same story in one line:

**Sign in → load samples (or IMAP sync, or upload) → read PDFs → summarise → classify → extract → human accept/override → done.**

### What “Sync email” does (extra)

```text
You connect IMAP (or Gmail, after Google verification)
        │
        ▼
  Sync now  (or automatic poll every ~2 minutes)
        │
        ▼
  New messages listed  →  each one fetched
        │
        ▼
  Same pipeline as Load sample emails
  (PDF → summary → classify → extract → queue)
```

---

## Live Gmail and “Send sample email”

**Send sample email**, **Gmail OAuth**, and **Gmail sync** are built. On the hosted API they wait for Google to finish verifying the Cloud app named `clinevo-api.onrender.com`. Until then Google shows this **Testing** screen — that is their process, not a missing button in our app:

> Access blocked: clinevo-api.onrender.com has not completed the Google verification process  
> Error 403: access_denied  
> The app is currently being tested, and can only be accessed by developer-approved testers.

What to use today:

| Path | Use it for |
|---|---|
| **Load sample emails** | The assignment walkthrough |
| **IMAP + Sync now** | Extra: real inbox without Google’s Gmail API review |
| **Upload PDF** | Extra / bonus: literature |
| **Send sample email** / Gmail OAuth | After Google verification of `clinevo-api.onrender.com` |
| **Email + password** | Sign in on the live site without that Google screen |

---

## How the pieces fit together

```text
  You (browser)
        │
        ▼
  Reviewer screens (Angular)          ← buttons, queue, PDF viewer, form
        │  talks to
        ▼
  API + background worker (Python)    ← reads mail/PDFs, calls AI, saves results
        │
        ├──► Database (Postgres)      ← messages, facts, reviews, audit log
        ├──► AI (OpenRouter)          ← summary, classify, extract, vision OCR
        └──► Optional live mail       ← IMAP read, or Gmail after verification
```

- **Angular** is the screen a reviewer uses. The assignment asked for Angular; we kept it.
- **Python (FastAPI)** is one service that does mail, PDFs, AI, and the waiting-line of jobs. The assignment suggested Java + a separate Python AI service; we used one Python API so OCR and AI could ship in a week. That choice is explained in [docs/WRITEUP.md](docs/WRITEUP.md).
- **Postgres** stores everything. The assignment suggested Oracle; the tables are ordinary rows and can move later.
- **A queue** (a waiting list inside the database) means a slow PDF does not freeze the screen. You still see progress in the pipeline strip.

---

## Codebase map (where to look)

You do not need this to *use* the app. It is here so anyone can find “the login”, “the AI”, or “the mail sync” without hunting.

```text
Clinevo/
├── frontend/                  Reviewer website (Angular)
│   └── src/app/
│       ├── pages/sign-in, sign-up, forgot-password, reset-password
│       ├── pages/inbox        Queue, Load sample emails, Advanced mail (IMAP / Gmail / Sync)
│       ├── pages/review       One case: email, PDF, fields, audit
│       └── core/              Login, API calls, types
│
├── backend/                   API + worker (Python)
│   └── app/
│       ├── main.py            Starts the API and the background worker
│       ├── routers/           HTTP doors: auth, mail, messages, uploads, jobs
│       ├── services/
│       │   ├── synthetic.py   Made-up emails and PDFs
│       │   ├── local_ingest.py  Load sample emails / upload PDF
│       │   ├── imap_client.py   Extra: IMAP connect and read
│       │   ├── gmail_client.py  Extra: Gmail OAuth read
│       │   ├── ingest.py        Turn a mailbox message into a queue item
│       │   ├── pdf_*.py         Flavour, extract, OCR, language
│       │   ├── ai_pipeline.py   Summary, classify, extract
│       │   ├── literature.py    Bonus: identifiable case? split
│       │   └── review.py        Accept / override / complete
│       ├── prompts.py         The instructions sent to the AI
│       ├── models.py          Database tables
│       └── jobqueue/          Waiting line: sync → PDF → AI
│
├── docs/                      Write-up, requirements map, submission email
├── docs/samples/              Made-up email JSON (the assignment test data)
└── artifacts/day6/pdfs/       The actual sample PDF files
```

| If you want to change… | Open |
|---|---|
| What the reviewer sees | `frontend/src/app/pages/` |
| Sign-in rules | `backend/app/routers/auth.py` |
| Load sample emails | `backend/app/services/local_ingest.py`, `synthetic.py` |
| IMAP / Sync | `backend/app/services/imap_client.py`, `routers/mail.py` |
| Gmail OAuth | `backend/app/services/gmail_client.py` |
| How PDFs are read | `backend/app/services/pdf_pipeline.py` |
| How the AI classifies | `backend/app/prompts.py`, `ai_pipeline.py` |
| What fields exist | `backend/app/constants.py` |

---

## Documents to send to Clinevo

Full checklist and a draft email: **[docs/SUBMISSION.md](docs/SUBMISSION.md)**.

| # | They asked for | In this repo |
|---|---|---|
| 1 | Working prototype | This app |
| 2 | Source code | This git repo |
| 3 | README | This file |
| 4 | Short write-up (2–5 pages) | [docs/WRITEUP.md](docs/WRITEUP.md) |
| 5 | Sample outputs | [docs/samples/](docs/samples/) and [artifacts/day6/](artifacts/day6/) — still export live JSON and capture screenshots |
| 6 | Bonus literature screening | Upload PDF → split |

Section-by-section match: **[docs/REQUIREMENTS.md](docs/REQUIREMENTS.md)**.

Email: pavithra.r@clinevotech.com, vivek.w@clinevotech.com, ashish.b@clinevotech.com, rehan.n@clinevotech.com

---

## What you need before you start

Install these on your computer. You only do this once.

| Thing | Required? | What it is, in everyday words | How to get it |
|---|---|---|---|
| **Python 3.12 or newer** | Yes | Runs the API (the engine behind the screens) | [python.org](https://www.python.org/downloads/) |
| **Node.js 18 or newer** | Yes | Runs the reviewer website | [nodejs.org](https://nodejs.org/) |
| **Postgres database** | Yes | Where messages and reviews are stored. A free [Neon](https://neon.tech/) project is enough | Copy the connection string Neon gives you |
| **OpenRouter API key** | Yes, for AI | The key used to summarise, classify, and read scans | [openrouter.ai](https://openrouter.ai/) → create a key |
| **Git** | Yes, to copy the repo | Downloads this project | [git-scm.com](https://git-scm.com/) |
| Google Cloud OAuth client | No | Only if you want “Continue with Google” on **localhost** | Steps below |
| SMTP settings | No | Only for “forgot password” email | Your mail provider or Amazon SES |
| Tesseract | No | Extra help reading scanned PDFs. The AI vision model still runs without it | macOS: `brew install tesseract` |

You do **not** need Gmail, IMAP, or Google verification to run the assignment demo. **Load sample emails** is enough.

---

## Run it on your laptop (step by step)

### 1. Copy the project

```bash
git clone https://github.com/Vivek-hash07/Clinevo-Assigment.git
cd Clinevo-Assigment
```

If you already have the folder, skip this and open a terminal in that folder.

### 2. Create the secret settings file

Copy `backend/.env.example` to `backend/.env`. **Never put this file on GitHub.**

```bash
cp backend/.env.example backend/.env
```

Open `backend/.env` and fill at least:

- `DATABASE_URL` — the Neon (or Postgres) connection string
- `JWT_SECRET` and `TOKEN_ENCRYPTION_KEY` — two long random strings
- `OPENROUTER_API_KEY` — your OpenRouter key

Create the two random strings with:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Run that twice. Paste one result as `JWT_SECRET` and the other as `TOKEN_ENCRYPTION_KEY`.

The rest of the file can stay as in the example for a local run. Full list:

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST/neondb?sslmode=require
JWT_SECRET=replace-with-a-long-random-hex-or-string
TOKEN_ENCRYPTION_KEY=replace-with-another-long-random-hex-or-string

FRONTEND_URL=http://localhost:8000
BACKEND_URL=http://localhost:8080
COOKIE_SECURE=false
COOKIE_SAMESITE=lax
APP_ENV=development

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8080/api/auth/google/callback

SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_USE_TLS=true

OPENROUTER_API_KEY=
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_VISION_MODEL=openai/gpt-4o-mini
```

| Setting | Required? | In everyday words |
|---|---|---|
| `DATABASE_URL` | Yes | Where messages and reviews are stored |
| `JWT_SECRET` | Yes | Signs your login cookie |
| `TOKEN_ENCRYPTION_KEY` | Yes | Locks IMAP / Gmail passwords in the database |
| `OPENROUTER_API_KEY` | Yes for AI | The key the AI calls use |
| `GOOGLE_CLIENT_ID` / `SECRET` | No | Only if you want Google sign-in on localhost |
| `SMTP_*` | No | Password-reset email; sending samples into a live mailbox |

Leave `GOOGLE_CLIENT_ID` empty if you will only use email/password. You can add Google later.

### 3. Start the API (terminal 1)

This creates the database tables the first time and starts the background worker (the “waiting line” that reads PDFs and calls the AI).

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --reload-dir app --port 8080 --host 0.0.0.0
```

On Windows PowerShell, use `backend\.venv\Scripts\Activate.ps1` instead of `source .venv/bin/activate`.

Leave this window open. Check http://localhost:8080/api/health — you should see a healthy response.

### 4. Start the reviewer website (terminal 2)

Open a **second** terminal:

```bash
cd frontend
npm install
npm start
```

Leave this window open too.

### 5. Open the app

1. In a browser go to **http://localhost:8000** (not `127.0.0.1`).
2. Click **Create an account** (email + password is the simplest).
3. You land on the inbox.
4. Click **Load sample emails**.
5. Wait until rows say **Ready** (the strip at the top shows progress).
6. Click a row. Accept or override fields.

If the queue stays empty: the API must be running on 8080, and `OPENROUTER_API_KEY` must be set. If the strip says the worker is stopped, restart terminal 1.

### Export the JSON the assignment asked for

After samples are **Ready**:

```bash
cd backend
source .venv/bin/activate
python -m app.scripts.batch_run --export --user-email you@example.com
```

Use the same email you signed up with. That writes `artifacts/day6/extracted/*.json` and `artifacts/day6/timings.csv`.

### Bonus: literature

Upload `artifacts/day6/pdfs/fictional-article-two-cases.pdf` from the inbox → **Screen article** → **Yes — identifiable** → **Split 2 cases**.

---

## How to connect IMAP and sync email (extra)

This is **not** required for the assignment. It is the extra path to read a **real** Gmail, Outlook, or Yahoo inbox **without** waiting for Google’s Gmail API verification.

IMAP is a standard way mail apps (Apple Mail, Outlook) talk to a mailbox. You give the app a special **app password**, not your normal login password. The app only **reads** mail; it does not send mail on this path.

### Gmail — create an app password

1. Open your Google Account → **Security**.
2. Turn on **2-Step Verification** if it is off (app passwords need it).
3. Search for **App passwords** (or go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)).
4. Create one. Name it anything (for example `Clinevo`).
5. Google shows a **16-character** password. Copy it. Spaces are fine; the app ignores them.

This is **not** the password you use to sign in to Gmail in the browser.

### In the app

1. Sign in at http://localhost:8000 (or the live site) with **email and password**.
2. On the inbox, click **Advanced mail**.
3. Under **IMAP / App password**:
   - **Your mailbox email** — the Gmail (or Outlook) address you want to read.
   - **Your app password** — the 16 characters from the step above.
   - **IMAP host** — leave blank for Gmail (`imap.gmail.com` is the default). For Outlook use `outlook.office365.com`. For Yahoo use `imap.mail.yahoo.com`.
   - **Folder** — leave `INBOX` unless you know you need another folder.
4. Click **Test connection**. You should see a success message.
5. Click **Connect my mailbox**.
6. Click **Sync now**.

New messages are fetched (sender, subject, date, body, PDF attachments). Non-PDFs are logged and skipped. Each message then goes through the same AI pipeline as **Load sample emails**. The inbox also polls about every **two minutes** while the API is running.

**Sync now** only appears after a mailbox is connected. If nothing arrives, check junk, that you used an **app password**, and that the pipeline strip is running.

---

## Google sign-in and Gmail — Testing mode

Google treats this Cloud app as **Testing** until they finish a formal verification. That is normal for a week-long prototype.

There are **two different Google buttons**. They are easy to mix up:

| Button | What it does | Works today? |
|---|---|---|
| **Continue with Google** on Sign in | Logs you into *this app* (name + email only) | On **localhost**, yes, if you set up an OAuth client (steps below). On the **live** site (`clinevo-api.onrender.com`), Google often shows Error 403 until testers are added or the app is published. Use **email + password** on the live site. |
| **Connect Gmail** under Advanced mail | Lets the app **read your Gmail inbox** (restricted `gmail.readonly` scope) | Waits on Google verification. Same Error 403 on the live API. Use **IMAP + Sync** instead. |

### What you will see (hosted API)

If you click Google on https://clienvo.vercel.app, Google may show:

> Access blocked: clinevo-api.onrender.com has not completed the Google verification process  
> The app is currently being tested, and can only be accessed by developer-approved testers.  
> Error 403: access_denied

That means the OAuth consent screen is still in **Testing**. It is not a bug in our login form. Until Google verification is complete:

- Sign in with **email and password**.
- Demo the product with **Load sample emails**.
- For a real inbox, use **IMAP + Sync** (section above).

### Optional: Google sign-in on your laptop only

Do this only if you want “Continue with Google” at http://localhost:8000.

1. Open [Google Cloud Console](https://console.cloud.google.com/) → create or pick a project.
2. **APIs & Services** → **OAuth consent screen**.
   - User type: **External**.
   - Publishing status will say **Testing**. That is expected.
   - Add your Gmail under **Test users**. Only those emails can click Continue with Google while status is Testing.
3. **APIs & Services** → **Credentials** → **Create credentials** → **OAuth client ID** → **Web application**.
4. **Authorized JavaScript origins:**
   ```text
   http://localhost:8000
   ```
5. **Authorized redirect URIs:**
   ```text
   http://localhost:8080/api/auth/google/callback
   ```
6. Copy the Client ID and Client secret into `backend/.env`:

   ```env
   GOOGLE_CLIENT_ID=....apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=....
   GOOGLE_REDIRECT_URI=http://localhost:8080/api/auth/google/callback
   ```

7. Restart the API (terminal 1). Sign in again at http://localhost:8000 → **Continue with Google**. Use an email you added as a **test user**.

Do **not** add the Gmail read scope (`gmail.readonly`) for this sign-in. That extra permission is what Google restricts until the app is verified. Reading a mailbox on localhost is what **IMAP** is for.

### If you later want one-click Gmail sync (after verification)

1. On the same Cloud project, enable the **Gmail API**.
2. Add test users, or publish / verify the app (Google’s restricted-scope review).
3. Add the **live** origin and redirect if you use Render:
   - Origin: `https://clienvo.vercel.app`
   - Redirect: `https://clinevo-api.onrender.com/api/auth/google/callback`
4. In the app: **Advanced mail** → **Connect Gmail** → **Sync now**.

Until that review is done, **IMAP + Sync** is the working live-mail extra.

---

## Hosting (optional)

- Reviewer screen: Vercel (`frontend/`). Set `API_URL` at build time (`frontend/scripts/write-prod-env.mjs`).
- API: Render (`render.yaml`). Production needs `APP_ENV=production`, `COOKIE_SECURE=true`, and HTTPS URLs.
- Render free-tier apps sleep; open `/api/health` once before a live demo.

The assignment suggested Angular → Spring Boot → Python AI → Oracle. This prototype is Angular → Python → Postgres, with IMAP and Gmail as extra mail doors. Full “why”: [docs/WRITEUP.md](docs/WRITEUP.md).
