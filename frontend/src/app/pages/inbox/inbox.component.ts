import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { Subscription, interval } from 'rxjs';

import { AuthService } from '../../core/auth.service';
import { QueueCounts, QueueItem } from '../../core/models';
import { QueueService } from '../../core/queue.service';

const EMPTY_COUNTS: QueueCounts = {
  pending: 0,
  processing: 0,
  ready: 0,
  reviewed: 0,
  total: 0,
};

@Component({
  selector: 'app-inbox',
  imports: [CommonModule],
  templateUrl: './inbox.component.html',
})
export class InboxComponent implements OnInit, OnDestroy {
  readonly auth = inject(AuthService);
  private readonly queue = inject(QueueService);

  readonly items = signal<QueueItem[]>([]);
  readonly counts = signal<QueueCounts>(EMPTY_COUNTS);
  readonly status = signal<string | null>(null);
  readonly loading = signal(true);
  readonly syncing = signal(false);
  readonly seeding = signal(false);
  readonly notice = signal('');
  readonly noticeKind = signal<'ok' | 'warn'>('ok');

  private poll?: Subscription;
  private pollTimer?: number;

  ngOnInit(): void {
    this.refresh();
  }

  ngOnDestroy(): void {
    this.poll?.unsubscribe();
    if (this.pollTimer) {
      window.clearTimeout(this.pollTimer);
    }
  }

  setStatus(value: string | null): void {
    this.status.set(value);
    this.refresh();
  }

  refresh(): void {
    this.queue.list(this.status()).subscribe({
      next: (res) => {
        this.items.set(res.items);
        this.counts.set(res.counts);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  syncMail(): void {
    if (this.syncing()) {
      return;
    }
    if (!this.auth.user()?.gmail_connected) {
      this.auth.startGoogle('gmail');
      return;
    }
    this.syncing.set(true);
    this.notice.set('');
    this.queue.syncMail().subscribe({
      next: (res) => {
        this.syncing.set(false);
        this.noticeKind.set(res.ok ? 'ok' : 'warn');
        this.notice.set(res.message);
        if (res.ok) {
          this.watchQueue();
        }
      },
      error: (err: HttpErrorResponse) => {
        this.syncing.set(false);
        this.noticeKind.set('warn');
        this.notice.set(this.readError(err, 'Could not queue mailbox sync. Is Inngest running?'));
      },
    });
  }

  seedMailbox(): void {
    if (this.seeding()) {
      return;
    }
    if (!this.auth.user()?.gmail_connected) {
      this.auth.startGoogle('gmail');
      return;
    }
    this.seeding.set(true);
    this.notice.set('');
    this.queue.seedSynthetic().subscribe({
      next: (res) => {
        this.seeding.set(false);
        this.noticeKind.set('ok');
        this.notice.set(res.message);
      },
      error: (err: HttpErrorResponse) => {
        this.seeding.set(false);
        this.noticeKind.set('warn');
        this.notice.set(this.readError(err, 'Could not send sample emails.'));
      },
    });
  }

  private watchQueue(): void {
    this.poll?.unsubscribe();
    if (this.pollTimer) {
      window.clearTimeout(this.pollTimer);
    }
    this.refresh();
    this.poll = interval(2500).subscribe(() => this.refresh());
    this.pollTimer = window.setTimeout(() => this.poll?.unsubscribe(), 20000);
  }

  private readError(err: HttpErrorResponse, fallback: string): string {
    const detail = err.error?.detail;
    return typeof detail === 'string' ? detail : fallback;
  }
}
