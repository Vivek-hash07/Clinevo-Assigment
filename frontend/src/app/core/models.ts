export interface AuthUser {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  google_linked: boolean;
  gmail_connected: boolean;
  auth_provider: string;
}

export interface AuthConfig {
  google_enabled: boolean;
  google_redirect_uri: string;
  frontend_url: string;
  gmail_scope: string;
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
}

export interface QueueDetail extends QueueItem {
  body: string;
  body_html: string | null;
  gmail_message_id: string | null;
  attachments: QueueAttachment[];
}

export interface SyncMailResult {
  ok: boolean;
  queued: boolean;
  gmail_connected: boolean;
  message: string;
  queued_event_ids?: string[];
}

export interface SeedSyntheticResult {
  ok: boolean;
  to: string;
  count: number;
  sent: string[];
  message: string;
}
