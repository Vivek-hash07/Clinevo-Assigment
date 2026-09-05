import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';

import { AuthService } from '../../core/auth.service';
import { QueueItem } from '../../core/models';

@Component({
  selector: 'app-inbox',
  imports: [CommonModule],
  templateUrl: './inbox.component.html',
})
export class InboxComponent implements OnInit {
  readonly auth = inject(AuthService);

  readonly items = signal<QueueItem[]>([]);
  readonly loading = signal(true);
  readonly syncing = signal(false);
  readonly notice = signal('');
  readonly noticeKind = signal<'ok' | 'warn'>('ok');

  ngOnInit(): void {
    this.auth.messages().subscribe({
      next: (rows) => {
        this.items.set(rows);
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
    this.auth.syncMail().subscribe({
      next: (res) => {
        this.syncing.set(false);
        this.noticeKind.set(res.ok ? 'ok' : 'warn');
        this.notice.set(res.message);
      },
      error: () => {
        this.syncing.set(false);
        this.noticeKind.set('warn');
        this.notice.set('Could not reach the server. Please try again.');
      },
    });
  }
}
