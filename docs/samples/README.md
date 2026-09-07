# Sample data and expected outputs

All mailbox and PDF samples are **synthetic**. There is no real patient, reporter, or product complaint.

## What the assignment asked for

| Requirement | What we ship |
|---|---|
| ≥ 10 emails with reaction detail | 14 |
| ≥ 5 digital PDFs | 14 |
| ≥ 2 scanned / handwritten PDFs | 2 |
| ≥ 5 fictional article PDFs | 5 |
| ≥ 2 non-English PDFs | 2 (Spanish, French) |
| ≥ 2 PQC-only and ≥ 2 MI-only | 3 PQC-only, 2 MI-only |
| ≥ 1 irrelevant / marketing | 2 |
| Extracted JSON per document | Export after the pipeline runs (see below) |
| Timing table for 10–15 documents | `artifacts/day6/timings.csv` after export |
| Screenshots or a short recording | Capture from the reviewer UI (see checklist) |

## Files in this folder

| Path | Contents |
|---|---|
| `catalog.json` | Index of every synthetic email, tags, and attachment names |
| `source/*.json` | Full made-up email body plus attachment metadata for each key |
| `extracted.schema.json` | Shape of the per-document JSON the pipeline exports |
| `../../artifacts/day6/pdfs/` | Binary PDFs (digital, scan-style, handwritten-style, articles, non-English) |

The 15-document **demo batch** (what **Load sample emails** queues) is listed in `catalog.json` as `demo_batch_keys`.

## Generate extracted JSON and timings

Sign in once so your reviewer account exists, keep FastAPI running, click **Load sample emails**, wait until items are **Ready**, then:

```bash
cd backend
source .venv/bin/activate
python -m app.scripts.batch_run --export --user-email you@example.com
```

That writes:

- `artifacts/day6/extracted/<fixture-key>.json` — classification, fields, citations, timings
- `artifacts/day6/timings.csv` and `timings.json` — `started_at` / `finished_at` / `duration_ms`
- `artifacts/day6/coverage.json` — required sample counts

Optional: rebuild PDFs without touching the database:

```bash
python -m app.scripts.batch_run --write-pdfs
```

## Screenshots / recording (you still need to capture these)

The assignment asks for screenshots or a 60–90 second screen recording of the review screen. Capture at least:

1. Sign-in, then the reviewer queue after **Load sample emails**
2. A ready ICSR case with extracted fields, confidence, and a source highlight
3. A dual-label case (cracked vial + rash)
4. A `"Not stated"` field the model refused to invent (`icsr-fatal-thin`)
5. Accept / override, then the audit trail
6. **Upload PDF** of `fictional-article-two-cases.pdf` and **Split** cases (bonus)

Put the files in `docs/samples/screenshots/` before you email the repo.

## Literature bonus PDFs

Upload from `artifacts/day6/pdfs/`:

- `fictional-article-two-cases.pdf` — two identifiable cases (split)
- `fictional-article-case-series.pdf` — three cases
- `fictional-article-methods-only.pdf` — no identifiable patient
