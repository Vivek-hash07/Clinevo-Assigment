export interface AuthUser {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  google_linked: boolean;
  gmail_connected: boolean;
  imap_connected?: boolean;
  mail_connected?: boolean;
  auth_provider: string;
}

export interface AuthConfig {
  google_enabled: boolean;
  google_redirect_uri: string;
  frontend_url: string;
  gmail_scope: string;
}

export interface Classification {
  category: string;
  confidence: number;
  reason: string;
}

export interface ExtractedField {
  id: string;
  field: string;
  label: string;
  value: string;
  confidence: number;
  source_type: string | null;
  source_id: string | null;
  source_quote: string | null;
  source_page: number | null;
  source_ref: string | null;
  locked: boolean;
  review_action: string | null;
  review_reason: string | null;
  reviewed_at: string | null;
}

export interface FieldGroup {
  id: string;
  title: string;
  fields: ExtractedField[];
}

export interface ReviewRecord {
  id: string;
  action: string;
  field_name: string | null;
  old_value: string | null;
  new_value: string | null;
  reason: string | null;
  user_id: string | null;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface PipelineRun {
  id: string;
  function_name: string;
  status: string;
  duration_ms: number | null;
  model: string | null;
  prompt_version: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface QueueItem {
  id: string;
  sender: string;
  subject: string;
  status: string;
  sent_at: string | null;
  snippet: string;
  pdf_count: number;
  skipped_attachment_count: number;
  summary?: string | null;
  relevant?: boolean | null;
  needs_human_review?: boolean;
  classifications?: Classification[];
  duration_ms?: number | null;
  last_error?: string | null;
  source?: string;
  fixture_key?: string | null;
  parent_message_id?: string | null;
}

export interface QueueCounts {
  pending: number;
  processing: number;
  ready: number;
  reviewed: number;
  total: number;
}

export interface QueueList {
  items: QueueItem[];
  counts: QueueCounts;
  status: string | null;
  limit: number;
  offset: number;
}

export interface QueueAttachment {
  id: string;
  filename: string;
  mime: string;
  skipped: boolean;
  skip_reason: string | null;
  size_bytes: number | null;
  processed: boolean;
  page_count?: number | null;
  document_flavor?: string | null;
  duration_ms?: number | null;
  extract_error?: string | null;
  has_file?: boolean;
}

export interface QueueDetail extends QueueItem {
  body: string;
  body_html: string | null;
  gmail_message_id: string | null;
  attachments: QueueAttachment[];
  extracted_fields: ExtractedField[];
  field_groups: FieldGroup[];
  reviews: ReviewRecord[];
  audit_events: AuditEvent[];
  pipeline_runs: PipelineRun[];
  relevance_reason?: string | null;
  ai_model?: string | null;
  ai_prompt_version?: string | null;
  ai_completed_at?: string | null;
  can_review: boolean;
  literature_identifiable?: boolean | null;
  literature_case_count?: number | null;
  literature_rationale?: string | null;
  literature_cases?: LiteratureCase[];
  literature_screened_at?: string | null;
  child_count?: number;
}

export interface LiteratureCase {
  index: number;
  summary: string;
  excerpt: string;
  source_ref: string;
}

export interface PdfPage {
  id: string;
  page_number: number;
  text: string;
  original_text: string;
  translated_text: string | null;
  language: string | null;
  language_confidence: number | null;
  ocr_confidence: number | null;
  llm_score: number | null;
  flavor: string | null;
  extract_method: string | null;
  column_count: number | null;
  tables: unknown[];
  image_notes: unknown[];
  needs_human_review: boolean;
  review_reasons: unknown[];
  source_ref: string | null;
}

export interface PdfPages {
  attachment_id: string;
  filename: string;
  document_flavor: string | null;
  processed: boolean;
  page_count: number | null;
  duration_ms: number | null;
  extract_error: string | null;
  pages: PdfPage[];
}

export interface ReviewRequest {
  action: 'accept' | 'override' | 'complete';
  field?: string | null;
  value?: string | null;
  reason?: string | null;
}

export interface SyncMailResult {
  ok: boolean;
  queued: boolean;
  mail_connected: boolean;
  gmail_connected?: boolean;
  message: string;
  providers?: string[];
  queued_event_ids?: string[];
}

export interface MailProviderStatus {
  provider: 'gmail' | 'imap';
  label: string;
  connected: boolean;
  sync_enabled: boolean;
  email: string | null;
  last_synced_at: string | null;
  last_error: string | null;
  host?: string | null;
  port?: number | null;
  folder?: string | null;
}

export interface MailStatus {
  connected: boolean;
  providers: MailProviderStatus[];
}

export interface ImapConnectResult {
  ok: boolean;
  host: string;
  port: number;
  folder: string;
  message_count: number;
  message: string;
}

export interface JobItem {
  id: string;
  kind: string;
  label: string;
  status: string;
  attempts: number;
  max_attempts: number;
  message_id: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  last_error: string | null;
}

export interface QueueHealth {
  worker_running: boolean;
  concurrency: number;
  processed: number;
  failed: number;
  uptime_seconds: number;
  mailbox_poll_seconds: number;
  counts: Record<string, number>;
  jobs: JobItem[];
}

export interface SeedSyntheticResult {
  ok: boolean;
  to: string;
  count: number;
  sent: string[];
  message: string;
}

export interface FixtureLoadResult {
  ok: boolean;
  queued: boolean;
  count: number;
  message_ids: string[];
  keys: string[];
  queued_event_ids?: string[];
  emailed_count?: number;
  emailed_to?: string | null;
  message: string;
}

export interface UploadResult {
  ok: boolean;
  queued: boolean;
  message_id: string;
  queued_event_ids?: string[];
  message: string;
}

export interface LiteratureSplitResult {
  ok: boolean;
  parent_id: string;
  child_ids: string[];
  queued_event_ids?: string[];
  message: string;
}
