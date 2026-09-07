export interface TextSpan {
  text: string;
  hit: boolean;
}

export interface CategoryChip {
  short: string;
  key: string;
  full: string;
}

export function categoryChip(category: string): CategoryChip {
  if (category.includes('ICSR')) {
    return { short: 'ICSR', key: 'icsr', full: category };
  }
  if (category.includes('PQC')) {
    return { short: 'PQC', key: 'pqc', full: category };
  }
  if (category.includes('(MI)') || category.includes('Info Request')) {
    return { short: 'MI', key: 'mi', full: category };
  }
  if (category.toLowerCase().includes('not relevant')) {
    return { short: 'Not relevant', key: 'nr', full: category };
  }
  return { short: category, key: 'other', full: category };
}

export function statusLabel(status: string | null | undefined): string {
  const labels: Record<string, string> = {
    pending: 'Pending',
    processing: 'Processing',
    ready: 'Ready',
    reviewed: 'Reviewed',
    error: 'Error',
    failed: 'Failed',
    queued: 'Queued',
    succeeded: 'Done',
    skipped: 'Skipped',
  };
  const key = (status || '').toLowerCase();
  return labels[key] || status || '';
}

export function sourceLabel(source: string | null | undefined): string {
  switch (source) {
    case 'fixture':
      return 'Sample';
    case 'upload':
      return 'Uploaded PDF';
    case 'split':
      return 'Split case';
    case 'gmail':
      return 'Gmail';
    case 'imap':
      return 'IMAP';
    default:
      return '';
  }
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms) || ms < 0) {
    return '';
  }
  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }
  const seconds = ms / 1000;
  if (seconds < 60) {
    return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const rem = Math.round(seconds % 60);
  return `${minutes}m ${rem}s`;
}

export function formatConfidence(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return '—';
  }
  return `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%`;
}

export function confidenceTone(value: number | null | undefined): 'low' | 'mid' | 'high' {
  const n = value ?? 0;
  if (n < 0.5) {
    return 'low';
  }
  if (n < 0.8) {
    return 'mid';
  }
  return 'high';
}

export function highlightSpans(source: string, quote: string | null | undefined): TextSpan[] {
  const text = source || '';
  const needle = (quote || '').trim();
  if (!text) {
    return [];
  }
  if (needle.length < 3) {
    return [{ text, hit: false }];
  }
  const direct = text.toLowerCase().indexOf(needle.toLowerCase());
  if (direct >= 0) {
    return splitAt(text, direct, needle.length);
  }
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+');
  try {
    const match = new RegExp(escaped, 'i').exec(text);
    if (match?.index != null) {
      return splitAt(text, match.index, match[0].length);
    }
  } catch {
    return [{ text, hit: false }];
  }
  return [{ text, hit: false }];
}

export function auditLabel(eventType: string): string {
  const labels: Record<string, string> = {
    'ai.understood': 'AI wrote the summary',
    'ai.classified': 'AI classified the message',
    'ai.extracted': 'AI extracted facts',
    'ai.failed': 'AI step failed',
    'review.accepted': 'Reviewer accepted a field',
    'review.overridden': 'Reviewer overrode a field',
    'review.completed': 'Reviewer completed the case',
    'ai.literature_screened': 'AI screened for patient cases',
    'review.literature_answered': 'Reviewer answered identifiable case?',
    'literature.split': 'Literature case split off',
    'literature.split_parent': 'Literature article split',
    'upload.received': 'PDF uploaded outside Gmail',
    'email.ingested': 'Message ingested',
  };
  return labels[eventType] || eventType.replace(/[._]/g, ' ');
}

function splitAt(text: string, start: number, length: number): TextSpan[] {
  return [
    { text: text.slice(0, start), hit: false },
    { text: text.slice(start, start + length), hit: true },
    { text: text.slice(start + length), hit: false },
  ].filter((part) => part.text.length > 0);
}
