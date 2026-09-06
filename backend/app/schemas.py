from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


def _validate_password(value: str) -> str:
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return value


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    _password_bytes = field_validator("password")(_validate_password)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=2048)
    password: str = Field(min_length=8, max_length=128)

    _password_bytes = field_validator("password")(_validate_password)


class UserOut(BaseModel):
    id: UUID
    email: str
    name: str
    avatar_url: str | None
    google_linked: bool
    gmail_connected: bool
    auth_provider: str

    model_config = {"from_attributes": True}


class AuthConfigOut(BaseModel):
    google_enabled: bool
    google_redirect_uri: str
    frontend_url: str
    gmail_scope: str


class HealthOut(BaseModel):
    status: str
    service: str
    db: str


class MessageOut(BaseModel):
    ok: bool
    message: str


class SyncMailOut(BaseModel):
    ok: bool
    queued: bool
    gmail_connected: bool
    message: str
    queued_event_ids: list[str] = []


class GmailStatusOut(BaseModel):
    connected: bool
    sync_enabled: bool
    gmail_email: str | None
    last_synced_at: str | None
    last_error: str | None


class SeedSyntheticOut(BaseModel):
    ok: bool
    to: str
    count: int
    sent: list[str]
    message: str


class LiteratureCaseOut(BaseModel):
    index: int
    summary: str
    excerpt: str
    source_ref: str = ""


class FixtureLoadOut(BaseModel):
    ok: bool
    queued: bool
    count: int
    message_ids: list[str]
    keys: list[str]
    queued_event_ids: list[str] = []
    message: str


class FixtureCoverageOut(BaseModel):
    emails_with_reaction: int
    digital_pdfs: int
    scanned_or_handwritten_pdfs: int
    article_pdfs: int
    non_english_pdfs: int
    pqc_only: int
    mi_only: int
    irrelevant: int
    catalog_size: int
    batch_size: int
    meets_day6: bool
    loaded_keys: list[str] = []
    templates: list[str] = []


class UploadOut(BaseModel):
    ok: bool
    queued: bool
    message_id: str
    queued_event_ids: list[str] = []
    message: str


class LiteratureAnswerRequest(BaseModel):
    identifiable: bool


class LiteratureSplitOut(BaseModel):
    ok: bool
    parent_id: str
    child_ids: list[str]
    queued_event_ids: list[str] = []
    message: str


class QueueCounts(BaseModel):
    pending: int = 0
    processing: int = 0
    ready: int = 0
    reviewed: int = 0
    total: int = 0


class QueueAttachmentOut(BaseModel):
    id: str
    filename: str
    mime: str
    skipped: bool
    skip_reason: str | None
    size_bytes: int | None
    processed: bool
    page_count: int | None = None
    document_flavor: str | None = None
    duration_ms: int | None = None
    extract_error: str | None = None
    has_file: bool = False


class PdfPageOut(BaseModel):
    id: str
    page_number: int
    text: str
    original_text: str
    translated_text: str | None = None
    language: str | None = None
    language_confidence: float | None = None
    ocr_confidence: float | None = None
    llm_score: float | None = None
    flavor: str | None = None
    extract_method: str | None = None
    column_count: int | None = None
    tables: list = []
    image_notes: list = []
    needs_human_review: bool = False
    review_reasons: list = []
    source_ref: str | None = None


class PdfPagesOut(BaseModel):
    attachment_id: str
    filename: str
    document_flavor: str | None = None
    processed: bool
    page_count: int | None = None
    duration_ms: int | None = None
    extract_error: str | None = None
    pages: list[PdfPageOut]


class ClassificationOut(BaseModel):
    category: str
    confidence: float
    reason: str


class ExtractedFieldOut(BaseModel):
    id: str
    field: str
    label: str
    value: str
    confidence: float
    source_type: str | None = None
    source_id: str | None = None
    source_quote: str | None = None
    source_page: int | None = None
    source_ref: str | None = None
    locked: bool = False
    review_action: str | None = None
    review_reason: str | None = None
    reviewed_at: str | None = None


class ReviewOut(BaseModel):
    id: str
    action: str
    field_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    reason: str | None = None
    user_id: str | None = None
    created_at: str


class AuditEventOut(BaseModel):
    id: str
    event_type: str
    payload: dict[str, Any] = {}
    created_at: str


class PipelineRunOut(BaseModel):
    id: str
    function_name: str
    status: str
    duration_ms: int | None = None
    model: str | None = None
    prompt_version: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class FieldGroupOut(BaseModel):
    id: str
    title: str
    fields: list[ExtractedFieldOut]


class ReviewRequest(BaseModel):
    action: Literal["accept", "override", "complete"]
    field: str | None = Field(default=None, max_length=128)
    value: str | None = Field(default=None, max_length=8000)
    reason: str | None = Field(default=None, max_length=2000)


class QueueItemOut(BaseModel):
    id: str
    sender: str
    subject: str
    status: str
    sent_at: str | None
    snippet: str = ""
    pdf_count: int = 0
    skipped_attachment_count: int = 0
    summary: str | None = None
    relevant: bool | None = None
    needs_human_review: bool = False
    classifications: list[ClassificationOut] = []
    duration_ms: int | None = None
    last_error: str | None = None
    source: str = "gmail"
    fixture_key: str | None = None
    parent_message_id: str | None = None


class QueueListOut(BaseModel):
    items: list[QueueItemOut]
    counts: QueueCounts
    status: str | None = None
    limit: int
    offset: int


class QueueDetailOut(QueueItemOut):
    body: str
    body_html: str | None = None
    gmail_message_id: str | None = None
    attachments: list[QueueAttachmentOut]
    extracted_fields: list[ExtractedFieldOut] = []
    field_groups: list[FieldGroupOut] = []
    reviews: list[ReviewOut] = []
    audit_events: list[AuditEventOut] = []
    pipeline_runs: list[PipelineRunOut] = []
    relevance_reason: str | None = None
    ai_model: str | None = None
    ai_prompt_version: str | None = None
    ai_completed_at: str | None = None
    can_review: bool = False
    literature_identifiable: bool | None = None
    literature_case_count: int | None = None
    literature_rationale: str | None = None
    literature_cases: list[LiteratureCaseOut] = []
    literature_screened_at: str | None = None
    child_count: int = 0
