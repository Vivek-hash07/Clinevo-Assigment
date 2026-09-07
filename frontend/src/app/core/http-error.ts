import { HttpErrorResponse } from '@angular/common/http';

export function readHttpError(err: HttpErrorResponse, fallback: string): string {
  const detail = err.error?.detail;
  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((item: { msg?: string }) => item?.msg)
      .filter((msg): msg is string => Boolean(msg))
      .join(' ');
  }
  if (err.status === 0) {
    return 'Cannot reach the API. Is the backend running on port 8080?';
  }
  if (err.status === 503) {
    return typeof detail === 'string' && detail.trim()
      ? detail
      : 'The database is temporarily unavailable. Wait a few seconds and try again.';
  }
  if (err.status === 401) {
    return 'Your session expired. Please sign in again.';
  }
  return fallback;
}
