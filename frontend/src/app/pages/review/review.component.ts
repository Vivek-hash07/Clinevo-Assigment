import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Subscription, interval } from 'rxjs';

import { AuthService } from '../../core/auth.service';
import { readHttpError } from '../../core/http-error';
import {
  AuditEvent,
  ExtractedField,
  PdfPage,
  PdfPages,
  QueueAttachment,
  QueueDetail,
} from '../../core/models';
import { QueueService } from '../../core/queue.service';
import {
  auditLabel,
  categoryChip,
  confidenceTone,
  formatConfidence,
  formatDuration,
  highlightSpans,
  sourceLabel,
  statusLabel,
} from '../../core/review.util';

@Component({
  selector: 'app-review',
  imports: [CommonModule, RouterLink, FormsModule],
  templateUrl: './review.component.html',
})
export class ReviewComponent implements OnInit, OnDestroy {
  readonly auth = inject(AuthService);
  private readonly queue = inject(QueueService);
  private readonly route = inject(ActivatedRoute);
  private readonly sanitizer = inject(DomSanitizer);

  readonly detail = signal<QueueDetail | null>(null);
  readonly loading = signal(true);
  readonly loadError = signal('');
  readonly saving = signal(false);
  readonly notice = signal('');
  readonly noticeKind = signal<'ok' | 'warn'>('ok');
  readonly selectedPdfId = signal<string | null>(null);
  readonly pdfUrl = signal<SafeResourceUrl | null>(null);
  readonly pdfMissing = signal(false);
  readonly pdfLoading = signal(false);
  readonly pages = signal<PdfPages | null>(null);
  readonly page = signal(1);
  readonly highlightQuote = signal<string | null>(null);
  readonly highlightTarget = signal<'email' | 'pdf' | null>(null);
  readonly editingField = signal<string | null>(null);
  readonly formError = signal('');

  draftValue = '';
  draftReason = '';

  private messageId = '';
  private objectUrl?: string;
  private poll?: Subscription;
  private routeSub?: Subscription;

  ngOnInit(): void {
    this.routeSub = this.route.paramMap.subscribe((params) => {
      const id = params.get('id') || '';
      if (id && id !== this.messageId) {
        this.messageId = id;
        this.resetView();
        this.load();
      }
    });
  }

  ngOnDestroy(): void {
    this.poll?.unsubscribe();
    this.routeSub?.unsubscribe();
    this.revokePdf();
  }

  load(): void {
    if (!this.messageId) {
      return;
    }
    this.loading.set(!this.detail());
    this.loadError.set('');
    this.queue.detail(this.messageId).subscribe({
      next: (detail) => this.applyDetail(detail, !this.detail()),
      error: (err: HttpErrorResponse) => {
        this.loading.set(false);
        this.stopPoll();
        this.loadError.set(readHttpError(err, 'Could not load this message.'));
      },
    });
  }

  pdfs(): QueueAttachment[] {
    return (this.detail()?.attachments || []).filter((item) => this.isPdf(item) && !item.skipped);
  }

  skipped(): QueueAttachment[] {
    return (this.detail()?.attachments || []).filter((item) => item.skipped);
  }

  selectedPdf(): QueueAttachment | undefined {
    const id = this.selectedPdfId();
    return this.pdfs().find((item) => item.id === id);
  }

  currentPage(): PdfPage | undefined {
    return this.pages()?.pages.find((item) => item.page_number === this.page());
  }

  emailSpans() {
    return highlightSpans(this.detail()?.body || '', this.highlightTarget() === 'email' ? this.highlightQuote() : null);
  }

  pageSpans() {
    const page = this.currentPage();
    const text = page?.text || page?.translated_text || page?.original_text || '';
    return highlightSpans(text, this.highlightTarget() === 'pdf' ? this.highlightQuote() : null);
  }

  chip(category: string) {
    return categoryChip(category);
  }

  confidence(value: number | null | undefined): string {
    return formatConfidence(value);
  }

  tone(value: number | null | undefined): string {
    return confidenceTone(value);
  }

  duration(ms: number | null | undefined): string {
    return formatDuration(ms);
  }

  statusText(status: string | null | undefined): string {
    return statusLabel(status);
  }

  sourceText(source: string | null | undefined): string {
    return sourceLabel(source);
  }

  pageTables(): Array<{ caption?: string; headers?: string[]; rows?: unknown[][] }> {
    const tables = this.currentPage()?.tables;
    if (!Array.isArray(tables)) {
      return [];
    }
    return tables.filter((item) => item && typeof item === 'object') as Array<{
      caption?: string;
      headers?: string[];
      rows?: unknown[][];
    }>;
  }

  pageImageNotes(): Array<{ kind?: string; caption?: string; needs_human_review?: boolean }> {
    const notes = this.currentPage()?.image_notes;
    if (!Array.isArray(notes)) {
      return [];
    }
    return notes.filter((item) => item && typeof item === 'object') as Array<{
      kind?: string;
      caption?: string;
      needs_human_review?: boolean;
    }>;
  }

  tableCell(value: unknown): string {
    if (value == null) {
      return '';
    }
    return String(value);
  }

  eventLabel(event: AuditEvent): string {
    return auditLabel(event.event_type);
  }

  eventDetail(event: AuditEvent): string {
    const payload = event.payload || {};
    const field = typeof payload['label'] === 'string' ? payload['label'] : payload['field'];
    const reason = payload['reason'];
    const bits: string[] = [];
    if (typeof field === 'string' && field) {
      bits.push(field);
    }
    if (typeof payload['old_value'] === 'string' && typeof payload['new_value'] === 'string') {
      bits.push(`${payload['old_value']} → ${payload['new_value']}`);
    }
    if (typeof reason === 'string' && reason) {
      bits.push(reason);
    }
    if (typeof payload['model'] === 'string') {
      bits.push(payload['model']);
    }
    return bits.join(' · ');
  }

  selectPdf(attachment: QueueAttachment): void {
    if (this.selectedPdfId() === attachment.id && this.pdfUrl()) {
      return;
    }
    this.selectedPdfId.set(attachment.id);
    this.page.set(1);
    this.loadPdf(attachment, 1);
  }

  setPage(next: number): void {
    const count = this.pageCount();
    const page = Math.min(Math.max(1, next), count);
    this.page.set(page);
    this.applyPdfHash(page);
  }

  pageCount(): number {
    return this.selectedPdf()?.page_count || this.pages()?.page_count || this.pages()?.pages.length || 1;
  }

  openSource(field: ExtractedField): void {
    this.highlightQuote.set(field.source_quote);
    if (field.source_type === 'pdf' && field.source_id) {
      this.highlightTarget.set('pdf');
      const attachment = this.pdfs().find((item) => item.id === field.source_id);
      const page = field.source_page || 1;
      if (attachment) {
        this.selectedPdfId.set(attachment.id);
        this.page.set(page);
        this.loadPdf(attachment, page);
      }
      this.scrollTo('pdf-cite');
      return;
    }
    this.highlightTarget.set('email');
    this.scrollTo('email-cite');
  }

  startOverride(field: ExtractedField): void {
    if (!this.detail()?.can_review || this.saving()) {
      return;
    }
    this.editingField.set(field.field);
    this.draftValue = field.value;
    this.draftReason = '';
    this.formError.set('');
  }

  cancelOverride(): void {
    this.editingField.set(null);
    this.formError.set('');
  }

  accept(field: ExtractedField): void {
    this.submit({ action: 'accept', field: field.field });
  }

  saveOverride(field: ExtractedField): void {
    this.formError.set('');
    const value = this.draftValue.trim();
    const reason = this.draftReason.trim();
    if (reason.length < 8) {
      this.formError.set('Override reason is required (at least 8 characters).');
      return;
    }
    if (!value) {
      this.formError.set('Override value is required.');
      return;
    }
    if (value === field.value) {
      this.formError.set('Override value must differ from the current value.');
      return;
    }
    this.submit({ action: 'override', field: field.field, value, reason });
  }

  complete(): void {
    if (!this.detail()?.can_review) {
      return;
    }
    this.submit({ action: 'complete' });
  }

  showLiterature(): boolean {
    const item = this.detail();
    if (!item) {
      return false;
    }
    if (item.source === 'upload' || item.source === 'split' || item.parent_message_id) {
      return true;
    }
    if ((item.fixture_key || '').startsWith('article-')) {
      return true;
    }
    if (item.literature_cases?.length || item.literature_identifiable != null) {
      return true;
    }
    return (item.attachments || []).some(
      (att) =>
        (att.document_flavor || '').toLowerCase() === 'article' ||
        (att.filename || '').toLowerCase().includes('article'),
    );
  }

  screenLiterature(): void {
    if (!this.messageId || this.saving()) {
      return;
    }
    this.saving.set(true);
    this.notice.set('');
    this.queue.screenLiterature(this.messageId).subscribe({
      next: (res) => {
        this.saving.set(false);
        this.noticeKind.set('ok');
        this.notice.set(res.message);
        this.startPoll();
      },
      error: (err: HttpErrorResponse) => {
        this.saving.set(false);
        this.noticeKind.set('warn');
        this.notice.set(readHttpError(err, 'Could not queue literature screening.'));
      },
    });
  }

  answerLiterature(identifiable: boolean): void {
    if (!this.messageId || this.saving()) {
      return;
    }
    this.saving.set(true);
    this.notice.set('');
    this.queue.answerLiterature(this.messageId, identifiable).subscribe({
      next: (detail) => {
        this.saving.set(false);
        this.noticeKind.set('ok');
        this.notice.set(
          identifiable
            ? 'Marked as an identifiable patient case. Split if more than one case is listed.'
            : 'Marked as not an identifiable patient case.',
        );
        this.applyDetail(detail, false);
      },
      error: (err: HttpErrorResponse) => {
        this.saving.set(false);
        this.noticeKind.set('warn');
        this.notice.set(readHttpError(err, 'Could not save the literature answer.'));
      },
    });
  }

  splitLiterature(): void {
    if (!this.messageId || this.saving()) {
      return;
    }
    this.saving.set(true);
    this.notice.set('');
    this.queue.splitLiterature(this.messageId).subscribe({
      next: (res) => {
        this.saving.set(false);
        this.noticeKind.set('ok');
        this.notice.set(res.message);
        this.load();
      },
      error: (err: HttpErrorResponse) => {
        this.saving.set(false);
        this.noticeKind.set('warn');
        this.notice.set(readHttpError(err, 'Could not split the article into cases.'));
      },
    });
  }

  private submit(body: { action: 'accept' | 'override' | 'complete'; field?: string; value?: string; reason?: string }): void {
    if (!this.messageId || this.saving()) {
      return;
    }
    this.saving.set(true);
    this.notice.set('');
    this.queue.review(this.messageId, body).subscribe({
      next: (detail) => {
        this.saving.set(false);
        this.editingField.set(null);
        this.formError.set('');
        this.noticeKind.set('ok');
        this.notice.set(
          body.action === 'complete'
            ? 'Case marked reviewed. Later AI runs will not overwrite accepted fields.'
            : body.action === 'override'
              ? 'Override saved and logged in the audit trail.'
              : 'Field accepted and locked.',
        );
        this.applyDetail(detail, false);
      },
      error: (err: HttpErrorResponse) => {
        this.saving.set(false);
        const message = readHttpError(err, 'Could not save the review action.');
        if (body.action === 'override') {
          this.formError.set(message);
        } else {
          this.noticeKind.set('warn');
          this.notice.set(message);
        }
      },
    });
  }

  private applyDetail(detail: QueueDetail, resetPdf = true): void {
    this.detail.set(detail);
    this.loading.set(false);
    const busy = detail.status === 'pending' || detail.status === 'processing';
    if (busy) {
      this.startPoll();
    } else {
      this.stopPoll();
    }
    const pdfs = this.pdfs();
    const keep = pdfs.find((item) => item.id === this.selectedPdfId());
    const next = keep || pdfs[0];
    if (!next) {
      this.selectedPdfId.set(null);
      this.revokePdf();
      this.pages.set(null);
      return;
    }
    if (resetPdf || !keep || !this.pdfUrl()) {
      this.selectedPdfId.set(next.id);
      this.loadPdf(next, this.page() || 1);
    }
  }

  private loadPdf(attachment: QueueAttachment, page: number): void {
    this.pdfLoading.set(true);
    this.pdfMissing.set(false);
    this.queue.pages(this.messageId, attachment.id).subscribe({
      next: (pages) => this.pages.set(pages),
      error: () => this.pages.set(null),
    });
    if (!attachment.has_file) {
      this.pdfLoading.set(false);
      this.pdfMissing.set(true);
      this.revokePdf();
      return;
    }
    this.queue.file(this.messageId, attachment.id).subscribe({
      next: (blob) => {
        this.pdfLoading.set(false);
        if (!blob.size || blob.type.includes('json')) {
          this.pdfMissing.set(true);
          this.revokePdf();
          return;
        }
        this.revokePdf();
        this.objectUrl = URL.createObjectURL(blob);
        this.page.set(page);
        this.applyPdfHash(page);
      },
      error: () => {
        this.pdfLoading.set(false);
        this.pdfMissing.set(true);
        this.revokePdf();
      },
    });
  }

  private applyPdfHash(page: number): void {
    if (!this.objectUrl) {
      this.pdfUrl.set(null);
      return;
    }
    this.pdfUrl.set(
      this.sanitizer.bypassSecurityTrustResourceUrl(`${this.objectUrl}#page=${page}&zoom=page-width`),
    );
  }

  private isPdf(item: QueueAttachment): boolean {
    return (item.mime || '').toLowerCase().includes('pdf') || item.filename.toLowerCase().endsWith('.pdf');
  }

  private startPoll(): void {
    if (this.poll) {
      return;
    }
    this.poll = interval(2500).subscribe(() => this.load());
  }

  private stopPoll(): void {
    this.poll?.unsubscribe();
    this.poll = undefined;
  }

  private resetView(): void {
    this.detail.set(null);
    this.notice.set('');
    this.editingField.set(null);
    this.highlightQuote.set(null);
    this.highlightTarget.set(null);
    this.pages.set(null);
    this.page.set(1);
    this.revokePdf();
    this.stopPoll();
  }

  private revokePdf(): void {
    if (this.objectUrl) {
      URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = undefined;
    }
    this.pdfUrl.set(null);
  }

  private scrollTo(id: string): void {
    window.setTimeout(() => {
      const hit = document.querySelector(`#${id} .source-hit`);
      (hit || document.getElementById(id))?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 50);
  }
}
