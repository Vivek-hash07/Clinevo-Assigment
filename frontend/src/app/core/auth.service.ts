import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, catchError, map, of, tap } from 'rxjs';

import { environment } from './environment';
import { AuthConfig, AuthUser, QueueItem, SyncMailResult } from './models';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly api = environment.apiUrl;
  private readonly userSignal = signal<AuthUser | null>(null);
  private readonly readySignal = signal(false);

  readonly user = this.userSignal.asReadonly();
  readonly ready = this.readySignal.asReadonly();
  readonly signedIn = computed(() => this.userSignal() !== null);

  constructor(
    private readonly http: HttpClient,
    private readonly router: Router,
  ) {}

  bootstrap(): Observable<AuthUser | null> {
    return this.http.get<AuthUser>(`${this.api}/api/auth/me`).pipe(
      tap((user) => {
        this.userSignal.set(user);
        this.readySignal.set(true);
      }),
      catchError((err: HttpErrorResponse) => {
        if (err.status === 401) {
          return this.http.post<AuthUser>(`${this.api}/api/auth/refresh`, {}).pipe(
            tap((user) => {
              this.userSignal.set(user);
              this.readySignal.set(true);
            }),
            catchError(() => {
              this.userSignal.set(null);
              this.readySignal.set(true);
              return of(null);
            }),
          );
        }
        this.userSignal.set(null);
        this.readySignal.set(true);
        return of(null);
      }),
    );
  }

  config(): Observable<AuthConfig> {
    return this.http.get<AuthConfig>(`${this.api}/api/auth/config`);
  }

  register(name: string, email: string, password: string): Observable<AuthUser> {
    return this.http
      .post<AuthUser>(`${this.api}/api/auth/register`, { name, email, password })
      .pipe(tap((user) => this.userSignal.set(user)));
  }

  login(email: string, password: string): Observable<AuthUser> {
    return this.http
      .post<AuthUser>(`${this.api}/api/auth/login`, { email, password })
      .pipe(tap((user) => this.userSignal.set(user)));
  }

  forgotPassword(email: string): Observable<{ ok: boolean; message: string }> {
    return this.http.post<{ ok: boolean; message: string }>(`${this.api}/api/auth/forgot-password`, {
      email,
    });
  }

  resetPassword(token: string, password: string): Observable<AuthUser> {
    return this.http
      .post<AuthUser>(`${this.api}/api/auth/reset-password`, { token, password })
      .pipe(tap((user) => this.userSignal.set(user)));
  }

  logout(): void {
    this.http.post(`${this.api}/api/auth/logout`, {}).subscribe({
      next: () => this.clearAndGo(),
      error: () => this.clearAndGo(),
    });
  }

  startGoogle(intent: 'signin' | 'signup' | 'gmail'): void {
    const next = '/inbox';
    window.location.href = `${this.api}/api/auth/google?intent=${intent}&next=${encodeURIComponent(next)}`;
  }

  messages(): Observable<QueueItem[]> {
    return this.http.get<QueueItem[]>(`${this.api}/api/messages`);
  }

  syncMail(): Observable<SyncMailResult> {
    return this.http.post<SyncMailResult>(`${this.api}/api/gmail/sync`, {});
  }

  isAuthenticated(): Observable<boolean> {
    if (this.readySignal()) {
      return of(this.userSignal() !== null);
    }
    return this.bootstrap().pipe(map((user) => user !== null));
  }

  private clearAndGo(): void {
    this.userSignal.set(null);
    void this.router.navigateByUrl('/sign-in');
  }
}
