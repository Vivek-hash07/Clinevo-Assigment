"""Day 6 helpers: write fixture PDFs, run a 10–15 document batch, export JSON + timings."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import session_scope
from app.models import Message, PipelineRun, User
from app.schema_sync import ensure_schema
from app.services.local_ingest import enqueue_message_pipeline, load_fixture_messages
from app.services.pdf_build import write_pdf
from app.services.synthetic import (
    batch_keys,
    catalog_coverage,
    required_coverage_ok,
    send_synthetic_mailbox,
    synthetic_catalog,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXPORT = ROOT / "artifacts" / "day6"


def write_fixture_pdfs(dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    seen: set[str] = set()
    for item in synthetic_catalog():
        for filename, mime, blob in item.attachments:
            if not filename.lower().endswith(".pdf"):
                continue
            if filename in seen:
                continue
            seen.add(filename)
            written.append(write_pdf(dest / filename, blob))
    return written


def coverage_payload() -> dict:
    coverage = catalog_coverage()
    coverage["meets_day6"] = required_coverage_ok(coverage)
    coverage["keys"] = [item.key for item in synthetic_catalog()]
    coverage["batch_keys"] = batch_keys()
    return coverage


def message_export(row: Message, runs: list[PipelineRun]) -> dict:
    fields = [
        {
            "field": item.field,
            "value": item.value,
            "confidence": item.confidence,
            "source_ref": item.source_ref,
            "source_type": item.source_type,
            "quote": item.source_quote,
        }
        for item in sorted(row.extracted_fields, key=lambda item: item.field)
    ]
    classifications = [
        {"category": item.category, "confidence": item.confidence, "reason": item.reason}
        for item in sorted(row.classifications, key=lambda item: item.category)
    ]
    timing = [
        {
            "function_name": item.function_name,
            "status": item.status,
            "duration_ms": item.duration_ms,
            "model": item.model,
            "prompt_version": item.prompt_version,
            "started_at": item.started_at.isoformat() if item.started_at else None,
            "finished_at": item.finished_at.isoformat() if item.finished_at else None,
        }
        for item in runs
    ]
    pdfs = [
        {
            "filename": item.filename,
            "flavor": item.document_flavor,
            "duration_ms": item.duration_ms,
            "page_count": item.page_count,
        }
        for item in row.attachments
        if not item.skipped
    ]
    total_ms = sum(item.duration_ms or 0 for item in runs)
    return {
        "id": row.id,
        "fixture_key": row.fixture_key,
        "source": row.source,
        "subject": row.subject,
        "status": row.status,
        "summary": row.summary,
        "relevant": row.relevant,
        "classifications": classifications,
        "fields": fields,
        "attachments": pdfs,
        "pipeline_runs": timing,
        "duration_ms_total": total_ms,
        "literature_identifiable": row.literature_identifiable,
        "literature_case_count": row.literature_case_count,
    }


def _load_rows(db, user_id: str, keys: list[str] | None) -> list[Message]:
    stmt = (
        select(Message)
        .options(
            selectinload(Message.attachments),
            selectinload(Message.classifications),
            selectinload(Message.extracted_fields),
        )
        .where(Message.user_id == user_id)
        .order_by(Message.created_at.asc())
    )
    if keys:
        stmt = stmt.where(Message.fixture_key.in_(keys))
    return list(db.scalars(stmt).all())


def export_batch(user_email: str, dest: Path, keys: list[str] | None = None) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    json_dir = dest / "extracted"
    json_dir.mkdir(parents=True, exist_ok=True)
    with session_scope() as db:
        user = db.scalar(select(User).where(User.email == user_email))
        if user is None:
            raise SystemExit(f"No user with email {user_email}")
        rows = _load_rows(db, user.id, keys)
        timing_rows: list[dict] = []
        exported: list[str] = []
        for row in rows:
            runs = list(
                db.scalars(
                    select(PipelineRun)
                    .where(PipelineRun.message_id == row.id)
                    .order_by(PipelineRun.started_at.asc().nullslast())
                ).all()
            )
            payload = message_export(row, runs)
            path = json_dir / f"{row.fixture_key or row.id}.json"
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            exported.append(str(path.relative_to(dest)))
            timing_rows.append(
                {
                    "fixture_key": row.fixture_key,
                    "subject": row.subject,
                    "status": row.status,
                    "duration_ms_total": payload["duration_ms_total"],
                    "pdf_flavors": ", ".join(
                        f"{item.filename}:{item.document_flavor or 'n/a'}"
                        for item in row.attachments
                        if not item.skipped
                    ),
                    "categories": ", ".join(item.category for item in row.classifications),
                    "field_count": len(row.extracted_fields),
                    "not_stated": sum(1 for item in row.extracted_fields if item.value == "Not stated"),
                }
            )
        (dest / "timings.json").write_text(json.dumps(timing_rows, indent=2), encoding="utf-8")
        lines = [
            "fixture_key,status,duration_ms_total,categories,field_count,not_stated,pdf_flavors",
        ]
        for item in timing_rows:
            lines.append(
                ",".join(
                    [
                        _csv(item.get("fixture_key")),
                        _csv(item.get("status")),
                        str(item.get("duration_ms_total") or 0),
                        _csv(item.get("categories")),
                        str(item.get("field_count") or 0),
                        str(item.get("not_stated") or 0),
                        _csv(item.get("pdf_flavors")),
                    ]
                )
            )
        (dest / "timings.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (dest / "coverage.json").write_text(json.dumps(coverage_payload(), indent=2), encoding="utf-8")
        return {"exported": exported, "count": len(rows), "dest": str(dest)}


def _csv(value: object) -> str:
    text = "" if value is None else str(value).replace('"', '""')
    if "," in text or '"' in text or "\n" in text:
        return f'"{text}"'
    return text


def wait_for_batch(user_email: str, keys: list[str], timeout_s: int) -> list[str]:
    deadline = time.time() + timeout_s
    pending = set(keys)
    while time.time() < deadline and pending:
        with session_scope() as db:
            user = db.scalar(select(User).where(User.email == user_email))
            if user is None:
                raise SystemExit(f"No user with email {user_email}")
            rows = db.scalars(
                select(Message).where(Message.user_id == user.id, Message.fixture_key.in_(list(pending)))
            ).all()
            for row in rows:
                if row.status in {"ready", "reviewed"}:
                    pending.discard(row.fixture_key)
        if pending:
            time.sleep(5)
    return sorted(pending)


def main() -> int:
    parser = argparse.ArgumentParser(description="Day 6 synthetic fixtures, batch run, and export.")
    parser.add_argument("--write-pdfs", action="store_true", help="Write catalog PDFs under artifacts/day6/pdfs")
    parser.add_argument("--export-dir", default=str(DEFAULT_EXPORT), help="Export directory")
    parser.add_argument("--user-email", help="Account that should own the local batch")
    parser.add_argument("--load", action="store_true", help="Insert the 15-document batch into Postgres and enqueue Inngest")
    parser.add_argument("--wait", type=int, default=0, help="Seconds to wait for ready status before export")
    parser.add_argument("--export", action="store_true", help="Write extracted JSON + timing table for the user")
    parser.add_argument("--mail", help="Also SMTP-send the batch to this Gmail address")
    parser.add_argument("--all", action="store_true", help="Load/send the full catalog instead of the 15-doc batch")
    args = parser.parse_args()

    dest = Path(args.export_dir)
    dest.mkdir(parents=True, exist_ok=True)
    coverage = coverage_payload()
    (dest / "coverage.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    print("Day 6 coverage:", json.dumps(coverage, indent=2))
    if not coverage["meets_day6"]:
        print("Coverage is below the Day 6 required counts.", file=sys.stderr)
        return 1

    if args.write_pdfs:
        paths = write_fixture_pdfs(dest / "pdfs")
        print(f"Wrote {len(paths)} PDFs to {dest / 'pdfs'}")

    keys = None if args.all else batch_keys()
    if args.mail:
        result = send_synthetic_mailbox(args.mail, keys)
        print(f"Sent {result['count']} messages to {result['to']}")

    if args.load:
        if not args.user_email:
            print("--load requires --user-email", file=sys.stderr)
            return 2
        ensure_schema()
        with session_scope() as db:
            user = db.scalar(select(User).where(User.email == args.user_email))
            if user is None:
                raise SystemExit(f"No user with email {args.user_email}. Sign in once first.")
            rows = load_fixture_messages(db, user, keys)
            for row in rows:
                if row.status in {"ready", "reviewed"}:
                    continue
                try:
                    enqueue_message_pipeline(str(user.id), row, retry=True)
                except Exception as exc:
                    print(f"Inngest enqueue failed for {row.fixture_key}: {exc}", file=sys.stderr)
            print(f"Loaded {len(rows)} messages for {args.user_email}")

    if args.wait:
        if not args.user_email:
            print("--wait requires --user-email", file=sys.stderr)
            return 2
        leftover = wait_for_batch(args.user_email, keys or batch_keys(), args.wait)
        if leftover:
            print(f"Still processing after {args.wait}s: {', '.join(leftover)}", file=sys.stderr)

    if args.export:
        if not args.user_email:
            print("--export requires --user-email", file=sys.stderr)
            return 2
        result = export_batch(args.user_email, dest, keys)
        print(f"Exported {result['count']} documents to {result['dest']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
