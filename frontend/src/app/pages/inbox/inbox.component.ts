import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription, interval } from 'rxjs';

import { AuthService } from '../../core/auth.service';
import { readHttpError } from '../../core/http-error';
import {
  Classification,
  JobItem,
  MailProviderStatus,
  QueueCounts,
  QueueItem,
} from '../../core/models';
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

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const MAX_UPLOAD_FILES = 12;

@Component({
  selector: 'app-inbox',
  imports: [CommonModule, RouterLink, FormsModule],
  templateUrl: './inbox.component.html',
})
export class InboxComponent implements OnInit, OnDestroy {
  readonly auth = inject(AuthService);
  private readonly queue = inject(QueueService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

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

  readonly mailProviders = signal<MailProviderStatus[]>([]);
  readonly mailConnected = signal(false);
  readonly showMailbox = signal(false);
  readonly testingImap = signal(false);
  readonly connectingImap = signal(false);
  readonly disconnectingImap = signal(false);
  readonly disconnectingGmail = signal(false);
  readonly workerRunning = signal(false);
  readonly recentJobs = signal<JobItem[]>([]);

  imapEmail = '';
  imapPassword = '';
  imapHost = '';
  imapFolder = 'INBOX';

  emailCopy = false;

  readonly mailboxLabel = computed(() => {
    const connected = this.mailProviders().filter((row) => row.connected && row.sync_enabled);
    if (!connected.length) {
      return 'Sample emails — no sync needed';
    }
    return connected
      .map((row) => `${row.label}${row.email ? ` · ${row.email}` : ''}`)
      .join(' · ');
  });

  readonly imapAccount = computed(
    () => this.mailProviders().find((row) => row.provider === 'imap') || null,
  );

  readonly gmailAccount = computed(
    () => this.mailProviders().find((row) => row.provider === 'gmail') || null,
  );

  private poll?: Subscription;
  private pollTimer?: number;

  ngOnInit(): void {
    const user = this.auth.user();
    this.imapEmail = user?.email || '';
    const mailFlag = this.route.snapshot.queryParamMap.get('mail');
    if (mailFlag === 'connected') {
      this.noticeKind.set('ok');
      this.notice.set('Your Gmail is connected. New messages are being synced into this queue.');
      this.watchQueue();
      void this.router.navigate([], { queryParams: {}, replaceUrl: true });
    } else if (mailFlag === 'denied') {
      this.showMailbox.set(true);
      this.noticeKind.set('warn');
      this.notice.set(
        'Google did not grant mailbox access for this account. Use IMAP below with your own app password, or add this email as a test user on the OAuth consent screen.',
      );
      void this.router.navigate([], { queryParams: {}, replaceUrl: true });
    }
    this.refresh();
    this.refreshMail();
    this.refreshJobs();
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

  refreshMail(): void {
    this.queue.mailStatus().subscribe({
      next: (res) => {
        this.mailProviders.set(res.providers);
        this.mailConnected.set(res.connected);
      },
      error: () => {
        const user = this.auth.user();
        this.mailConnected.set(Boolean(user?.mail_connected || user?.gmail_connected || user?.imap_connected));
      },
    });
  }

  refreshJobs(): void {
    this.queue.jobs(8).subscribe({
      next: (res) => {
        this.workerRunning.set(res.worker_running);
        this.recentJobs.set(res.jobs);
      },
      error: () => undefined,
    });
  }

  syncMail(): void {
    if (this.syncing()) {
      return;
    }
    if (!this.mailConnected()) {
      this.showMailbox.set(true);
      this.noticeKind.set('warn');
      this.notice.set(
        'Connect a mailbox first. IMAP + a Gmail app password is the supported path (no Google API verification).',
      );
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
        this.notice.set(readHttpError(err, 'Could not queue mailbox sync.'));
      },
    });
  }

  seedMailbox(): void {
    if (this.seeding()) {
      return;
    }
    if (!this.mailConnected()) {
      this.showMailbox.set(true);
      this.noticeKind.set('warn');
      this.notice.set(
        'Mailbox sync is optional. Use Load sample emails for the assignment batch, or open Advanced to connect your inbox.',
      );
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
        this.notice.set(readHttpError(err, 'Could not send sample emails. Use Load sample emails instead.'));
      },
    });
  }

  loadFixtures(): void {
    if (this.loadingFixtures()) {
      return;
    }
    this.loadingFixtures.set(true);
    this.notice.set('');
    this.queue.loadFixtures(this.emailCopy).subscribe({
      next: (res) => {
        this.loadingFixtures.set(false);
        this.noticeKind.set(res.ok ? 'ok' : 'warn');
        this.notice.set(res.message);
        this.watchQueue(180000);
      },
      error: (err: HttpErrorResponse) => {
        this.loadingFixtures.set(false);
        this.noticeKind.set('warn');
        this.notice.set(readHttpError(err, 'Could not load sample emails.'));
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
    if (files.length > MAX_UPLOAD_FILES) {
      this.noticeKind.set('warn');
      this.notice.set(`Upload at most ${MAX_UPLOAD_FILES} PDFs at a time.`);
      return;
    }
    const invalid = files.find((file) => !file.name.toLowerCase().endsWith('.pdf'));
    if (invalid) {
      this.noticeKind.set('warn');
      this.notice.set(`${invalid.name} is not a PDF. Only PDF files are processed.`);
      return;
    }
    const empty = files.find((file) => file.size === 0);
    if (empty) {
      this.noticeKind.set('warn');
      this.notice.set(`${empty.name} is empty.`);
      return;
    }
    const tooBig = files.find((file) => file.size > MAX_UPLOAD_BYTES);
    if (tooBig) {
      this.noticeKind.set('warn');
      this.notice.set(`${tooBig.name} is larger than 20 MB.`);
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

  testImap(): void {
    if (this.testingImap()) {
      return;
    }
    const body = this.imapPayload();
    if (!body) {
      return;
    }
    this.testingImap.set(true);
    this.notice.set('');
    this.queue.testImap(body).subscribe({
      next: (res) => {
        this.testingImap.set(false);
        this.noticeKind.set('ok');
        this.notice.set(res.message);
      },
      error: (err: HttpErrorResponse) => {
        this.testingImap.set(false);
        this.noticeKind.set('warn');
        this.notice.set(readHttpError(err, 'Could not reach the IMAP server.'));
      },
    });
  }

  connectImap(): void {
    if (this.connectingImap()) {
      return;
    }
    const body = this.imapPayload();
    if (!body) {
      return;
    }
    this.connectingImap.set(true);
    this.notice.set('');
    this.queue.connectImap(body).subscribe({
      next: (res) => {
        this.connectingImap.set(false);
        this.noticeKind.set('ok');
        this.notice.set(res.message);
        this.imapPassword = '';
        this.refreshMail();
        this.watchQueue();
      },
      error: (err: HttpErrorResponse) => {
        this.connectingImap.set(false);
        this.noticeKind.set('warn');
        this.notice.set(readHttpError(err, 'Could not connect the IMAP mailbox.'));
      },
    });
  }

  disconnectImap(): void {
    if (this.disconnectingImap()) {
      return;
    }
    this.disconnectingImap.set(true);
    this.queue.disconnectImap().subscribe({
      next: (res) => {
        this.disconnectingImap.set(false);
        this.noticeKind.set('ok');
        this.notice.set(res.message);
        this.refreshMail();
      },
      error: (err: HttpErrorResponse) => {
        this.disconnectingImap.set(false);
        this.noticeKind.set('warn');
        this.notice.set(readHttpError(err, 'Could not disconnect IMAP.'));
      },
    });
  }

  connectGmail(): void {
    this.auth.startGoogle('gmail');
  }

  disconnectGmail(): void {
    if (this.disconnectingGmail()) {
      return;
    }
    this.disconnectingGmail.set(true);
    this.queue.disconnectGmail().subscribe({
      next: (res) => {
        this.disconnectingGmail.set(false);
        this.noticeKind.set('ok');
        this.notice.set(res.message);
        this.refreshMail();
      },
      error: (err: HttpErrorResponse) => {
        this.disconnectingGmail.set(false);
        this.noticeKind.set('warn');
        this.notice.set(readHttpError(err, 'Could not disconnect Gmail.'));
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

  jobDuration(job: JobItem): string {
    return formatDuration(job.duration_ms);
  }

  private imapPayload(): { email: string; app_password: string; host?: string; folder?: string } | null {
    const email = this.imapEmail.trim();
    const password = this.imapPassword.trim();
    if (!email || !password) {
      this.noticeKind.set('warn');
      this.notice.set('Enter the mailbox email and a 16-character Gmail app password.');
      return null;
    }
    const body: { email: string; app_password: string; host?: string; folder?: string } = {
      email,
      app_password: password,
    };
    if (this.imapHost.trim()) {
      body.host = this.imapHost.trim();
    }
    if (this.imapFolder.trim()) {
      body.folder = this.imapFolder.trim();
    }
    return body;
  }

  private watchQueue(ms = 20000): void {
    this.poll?.unsubscribe();
    if (this.pollTimer) {
      window.clearTimeout(this.pollTimer);
    }
    this.refresh();
    this.refreshJobs();
    this.refreshMail();
    this.poll = interval(2500).subscribe(() => {
      this.refresh();
      this.refreshJobs();
    });
    this.pollTimer = window.setTimeout(() => this.poll?.unsubscribe(), ms);
  }
}
