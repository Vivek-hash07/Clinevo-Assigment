# What to submit

The assignment lists **six deliverables**. Send the repo (or zip) and these files to the four addresses below. Deadline: 7–10 days from when you received `Clinevo_Assignment.pdf`. A 15–20 minute live walkthrough will be scheduled after that.

## Recipients

- pavithra.r@clinevotech.com
- vivek.w@clinevotech.com
- ashish.b@clinevotech.com
- rehan.n@clinevotech.com

Questions: pavithra.r@clinevotech.com

## Checklist

| # | Deliverable | Status in this repo | What you still do |
|---|---|---|---|
| 1 | Working prototype | Code runs locally (see root README). Hosted UI/API if you deployed them. | Confirm the live URL still boots. Render may sleep; open the API health check once before the demo. |
| 2 | Source code | GitHub: https://github.com/Vivek-hash07/Clinevo-Assigment | Make sure `main` is pushed. Do **not** commit `.env`. |
| 3 | README | Root `README.md` — local run, env placeholders, what works / what does not | Read it once so you can talk through setup. |
| 4 | Short write-up (2–5 pages) | `docs/WRITEUP.md` | Export to PDF if they prefer a file attachment (`docs/WRITEUP.md`). |
| 5 | Sample outputs | Source catalog + PDFs are in `docs/samples/` and `artifacts/day6/pdfs/`. | **Required from you:** (a) export live extracted JSON after **Load sample emails**, (b) screenshots or a 60–90s recording of the review screen. |
| 6 | Bonus (optional) | Literature upload / screen / split is implemented | Include one screenshot of the two-case article split. |

### 5a — Extracted JSON (after you run the app)

```bash
# FastAPI must be running. Sign in once, click Load sample emails, wait until Ready.
cd backend
source .venv/bin/activate
python -m app.scripts.batch_run --export --user-email YOUR_LOGIN_EMAIL
```

Attach or leave in the repo:

- `artifacts/day6/extracted/*.json`
- `artifacts/day6/timings.csv`

### 5b — Screenshots / recording (you capture these)

Save under `docs/samples/screenshots/` (create the folder):

1. Reviewer queue with sample emails loaded
2. ICSR case with fields, confidence, and a highlighted source
3. Dual-label case (`icsr-dual-defect`)
4. `"Not stated"` on the thin fatal case
5. Override + audit trail
6. Literature split on `fictional-article-two-cases.pdf`

A single 60–90 second screen recording can replace most of these.

## Suggested email

Subject: `Smart Inbox Assistant — submission (Forward Deployment / GenAI)`

```text
Hello,

Please find my Smart Inbox Assistant prototype for the Forward Deployment /
GenAI Integration Engineer assignment.

Repo: https://github.com/Vivek-hash07/Clinevo-Assigment
Live UI: https://clienvo.vercel.app
API health: https://clinevo-api.onrender.com/api/health

README (local setup): /README.md
Write-up: /docs/WRITEUP.md
Requirements map: /docs/REQUIREMENTS.md
Synthetic samples: /docs/samples/
Extracted JSON + timings: /artifacts/day6/   (after the batch export)
Literature bonus: Upload PDF on the queue, then split multi-case articles.

How to demo in 15 minutes:
1. Sign in with email/password (or Google on localhost) → Load sample emails.
   Live Gmail send/sync waits on Google verification of clinevo-api.onrender.com
   (Error 403 while the OAuth app is in Testing). That is expected; the
   assignment’s synthetic samples are the demo path.
2. Open the cracked-vial + rash case (ICSR + PQC).
3. Open the thin fatal case and show "Not stated".
4. Override one field and show the audit row.
5. Upload fictional-article-two-cases.pdf and split the two cases.

Send sample email and Gmail OAuth are implemented for after Google
completes verification of clinevo-api.onrender.com. Until then, Load
sample emails runs the same pipeline the assignment asks for.

All data is fictional. No real patient information was used.

Thank you,
Vivek Sarvaiya
```

Replace the live URLs if they have changed. If Render is asleep, note that the first request may take a minute.

## Walkthrough script (15–20 min)

1. Open the live app → sign in with email/password (Google on the hosted API waits on verification of `clinevo-api.onrender.com`).
2. Click **Load sample emails**. Show the queue filling (Pending → Processing → Ready). Mention that Send sample email / Gmail OAuth are the post-verification path; Error 403 today is Google Testing, not a missing pipeline.
3. Open a scanned or handwritten card: flavor, OCR confidence, page cite.
4. Open **Cracked vial and then a rash**: both ICSR and PQC chips, reasons, photo-mentioned field.
5. Open the sparse death report: most fields `"Not stated"`.
6. Override one field with a reason → audit trail.
7. Upload `fictional-article-two-cases.pdf` → identifiable yes → split.
8. One sentence on stack: *Python because OCR/LLM are the product; Angular because that is the reviewer surface; Postgres because it maps to Oracle; Load sample emails because the assignment asks for synthetic data and Google verification of clinevo-api.onrender.com is the production Gmail step.*
