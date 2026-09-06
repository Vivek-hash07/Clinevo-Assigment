"""Literature screening: identifiable patient case? Split multi-case articles."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ai_contracts import PROMPT_SPECS
from app.config import get_settings
from app.constants import (
    FLAVOR_ARTICLE,
    PROMPT_LITERATURE,
    SOURCE_SPLIT,
    SOURCE_UPLOAD,
    STATUS_REVIEWED,
)
from app.models import Attachment, Message, User
from app.services.ai_pack import build_message_pack, load_message_for_ai
from app.services.ai_pipeline import _finish_run, _start_run, _structured_call
from app.services.audit import write_audit
from app.services.llm import LlmError
from app.services.local_ingest import copy_attachment_with_pages


def _cases_from_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "").strip()
        excerpt = str(item.get("excerpt") or "").strip()
        if not (summary or excerpt):
            continue
        try:
            case_index = int(item.get("index") or index)
        except (TypeError, ValueError):
            case_index = index
        out.append(
            {
                "index": case_index,
                "summary": summary[:500],
                "excerpt": excerpt[:4000],
                "source_ref": str(item.get("source_ref") or "")[:255],
            }
        )
    return out


def should_auto_screen(message: Message) -> bool:
    if message.parent_message_id or message.source == SOURCE_SPLIT:
        return False
    if message.source == SOURCE_UPLOAD:
        return True
    for attachment in message.attachments:
        if (attachment.document_flavor or "") == FLAVOR_ARTICLE:
            return True
        name = (attachment.filename or "").lower()
        if "article" in name or "letter" in name or "series" in name:
            return True
    return False


def screen_literature(message_id: str, inngest_run_id: str | None = None) -> dict[str, Any]:
    from app.database import session_scope

    settings = get_settings()
    started = datetime.now(UTC)
    with session_scope() as db:
        message = load_message_for_ai(db, message_id)
        run = _start_run(
            db,
            function_name="ai/literature-screen",
            message_id=message_id,
            prompt_version=PROMPT_LITERATURE,
            inngest_run_id=inngest_run_id,
            started=started,
        )
        if message is None:
            _finish_run(run, status="skipped", started=started)
            return {"ok": False, "skip": True, "reason": "missing_message"}
        if message.status == STATUS_REVIEWED:
            _finish_run(run, status="skipped", started=started)
            return {"ok": True, "skip": True, "reason": "reviewed", "message_id": message_id}
        if message.literature_screened_at is not None and message.literature_cases is not None:
            _finish_run(run, status="skipped", started=started, model=message.ai_model)
            return {
                "ok": True,
                "skip": True,
                "reason": "already_screened",
                "message_id": message_id,
                "identifiable": message.literature_identifiable,
                "case_count": message.literature_case_count,
            }

        pack = build_message_pack(message, settings)
        client = get_llm_client()
        spec = PROMPT_SPECS[PROMPT_LITERATURE]
        try:
            llm = _structured_call(client, spec, pack.text, settings)
        except LlmError as exc:
            _finish_run(run, status="failed", started=started)
            if not exc.retryable:
                return {"ok": False, "reason": str(exc), "message_id": message.id}
            raise

        data = llm.data if isinstance(llm.data, dict) else {}
        cases = _cases_from_payload(data)
        identifiable = bool(data.get("identifiable_patient_case")) and len(cases) > 0
        if not identifiable:
            cases = []
        message.literature_identifiable = identifiable
        message.literature_case_count = len(cases)
        message.literature_rationale = str(data.get("rationale") or "")[:2000]
        message.literature_cases = cases
        message.literature_screened_at = datetime.now(UTC)
        duration_ms = _finish_run(run, status="succeeded", started=started, model=llm.model)
        write_audit(
            db,
            "ai.literature_screened",
            message.user_id,
            {
                "prompt_version": PROMPT_LITERATURE,
                "model": llm.model,
                "duration_ms": duration_ms,
                "identifiable": identifiable,
                "case_count": len(cases),
            },
            message_id=message.id,
        )
        return {
            "ok": True,
            "message_id": message.id,
            "user_id": message.user_id,
            "identifiable": identifiable,
            "case_count": len(cases),
        }


def apply_human_answer(db: Session, user: User, message: Message, identifiable: bool) -> Message:
    message.literature_identifiable = identifiable
    if not identifiable:
        message.literature_case_count = 0
    elif message.literature_cases:
        message.literature_case_count = len(message.literature_cases)
    write_audit(
        db,
        "review.literature_answered",
        user.id,
        {"identifiable": identifiable, "case_count": message.literature_case_count},
        message_id=message.id,
    )
    return message


def split_literature_cases(db: Session, user: User, parent: Message) -> list[Message]:
    if parent.user_id != user.id:
        raise ValueError("Message not found")
    existing = db.scalars(select(Message).where(Message.parent_message_id == parent.id)).all()
    if existing:
        return list(existing)
    cases = list(parent.literature_cases or [])
    if not parent.literature_identifiable or len(cases) < 2:
        raise ValueError("Split needs an identifiable article with at least two patient cases.")

    parent_loaded = db.scalar(
        select(Message)
        .options(selectinload(Message.attachments).selectinload(Attachment.pages))
        .where(Message.id == parent.id)
    )
    assert parent_loaded is not None
    created: list[Message] = []
    pdfs = [item for item in parent_loaded.attachments if not item.skipped and item.storage_key]
    for case in cases:
        index = int(case.get("index") or (len(created) + 1))
        summary = str(case.get("summary") or f"Case {index}")
        excerpt = str(case.get("excerpt") or "")
        body = (
            f"Split from uploaded literature ({parent_loaded.subject}). "
            f"Fictional / synthetic case {index} of {len(cases)}.\n\n"
            f"Summary: {summary}\n\n"
            f"Excerpt:\n{excerpt}\n"
        )
        child = Message(
            user_id=user.id,
            source=SOURCE_SPLIT,
            parent_message_id=parent_loaded.id,
            fixture_key=f"split:{parent_loaded.id}:{index}",
            sender=parent_loaded.sender,
            subject=f"{parent_loaded.subject} — case {index}"[:1024],
            sent_at=datetime.now(UTC),
            snippet=summary[:2048],
            body=body[: get_settings().message_body_max_chars],
            status=STATUS_PROCESSING,
            literature_identifiable=True,
            literature_case_count=1,
            literature_rationale=f"Split case {index} from parent {parent_loaded.id}",
            literature_cases=[case],
            literature_screened_at=datetime.now(UTC),
        )
        db.add(child)
        db.flush()
        for attachment in pdfs:
            copy_attachment_with_pages(db, attachment, child)
        write_audit(
            db,
            "literature.split",
            user.id,
            {"parent_id": parent_loaded.id, "case_index": index, "summary": summary},
            message_id=child.id,
        )
        created.append(child)
    write_audit(
        db,
        "literature.split_parent",
        user.id,
        {"child_ids": [row.id for row in created], "case_count": len(created)},
        message_id=parent_loaded.id,
    )
    return created
