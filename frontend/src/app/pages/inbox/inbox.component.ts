import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Subscription, interval } from 'rxjs';

import { AuthService } from '../../core/auth.service';
import { readHttpError } from '../../core/http-error';
import { Classification, QueueCounts, QueueItem } from '../../core/models';
import { QueueService } from '../../core/queue.service';
import {
  categoryChip,
  confidenceTone,
  formatConfidence,
  formatDuration,
} from '../../core/review.util';

const EMPTY_COUNTS: QueueCounts = {
  pending: 0,
  processing: 0,
  ready: 0,
  reviewed: 0,
  total: 0,
};

@Component({
  selector: 'app-inbox',
  imports: [CommonModule, RouterLink],
  templateUrl: './inbox.component.html',
})
export class InboxComponent implements OnInit, OnDestroy {
  readonly auth = inject(AuthService);
  private readonly queue = inject(QueueService);

  readonly items = signal<QueueItem[]>([]);
  readonly counts = signal<QueueCounts>(EMPTY_COUNTS);
  readonly status = signal<string | null>(null);
  readonly loading = signal(true);
  readonly loadError = signal('');
  readonly syncing = signal(false);
  readonly seeding = signal(false);
  readonly loadingFixtures = signal(false);
  readonly uploading = signal(false);
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
    this.loading.set(true);
    this.refresh();
  }

  refresh(): void {
    this.loadError.set('');
    this.queue.list(this.status()).subscribe({
      next: (res) => {
        this.items.set(res.items);
        this.counts.set(res.counts);
        this.loading.set(false);
      },
      error: (err: HttpErrorResponse) => {
        this.loading.set(false);
        this.loadError.set(readHttpError(err, 'Could not load the reviewer queue.'));
      },
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
        this.notice.set(readHttpError(err, 'Could not queue mailbox sync. Is Inngest running?'));
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
        this.notice.set(readHttpError(err, 'Could not send sample emails.'));
      },
    });
  }

  loadFixtures(): void {
    if (this.loadingFixtures()) {
      return;
    }
    this.loadingFixtures.set(true);
    this.notice.set('');
    this.queue.loadFixtures().subscribe({
      next: (res) => {
        this.loadingFixtures.set(false);
        this.noticeKind.set(res.ok ? 'ok' : 'warn');
        this.notice.set(res.message);
        this.watchQueue(180000);
      },
      error: (err: HttpErrorResponse) => {
        this.loadingFixtures.set(false);
        this.noticeKind.set('warn');
        this.notice.set(readHttpError(err, 'Could not load local fixtures. Is Inngest running?'));
      },
    });
  }

  uploadPdfs(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = Array.from(input.files || []);
    input.value = '';
    if (!files.length || this.uploading()) {
      return;
    }
    this.uploading.set(true);
    this.notice.set('');
    this.queue.uploadPdfs(files).subscribe({
      next: (res) => {
        this.uploading.set(false);
        this.noticeKind.set('ok');
        this.notice.set(res.message);
        this.watchQueue(180000);
      },
      error: (err: HttpErrorResponse) => {
        this.uploading.set(false);
        this.noticeKind.set('warn');
        this.notice.set(readHttpError(err, 'Could not upload the PDF.'));
      },
    });
  }

  chip(label: Classification) {
    return categoryChip(label.category);
  }

  confidence(label: Classification): string {
    return formatConfidence(label.confidence);
  }

  tone(label: Classification): string {
    return confidenceTone(label.confidence);
  }

  duration(item: QueueItem): string {
    return formatDuration(item.duration_ms);
  }

  summaryLine(item: QueueItem): string {
    const text = (item.summary || item.snippet || '').replace(/\s+/g, ' ').trim();
    return text;
  }

  private watchQueue(ms = 20000): void {
    this.poll?.unsubscribe();
    if (this.pollTimer) {
      window.clearTimeout(this.pollTimer);
    }
    this.refresh();
    this.poll = interval(2500).subscribe(() => this.refresh());
    this.pollTimer = window.setTimeout(() => this.poll?.unsubscribe(), ms);
  }
}
