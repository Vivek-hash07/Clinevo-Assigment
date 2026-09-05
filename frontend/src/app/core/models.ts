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
}

export interface SyncMailResult {
  ok: boolean;
  queued: boolean;
  gmail_connected: boolean;
  message: string;
}
