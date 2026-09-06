import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from './environment';
import {
  PdfPages,
  QueueDetail,
  QueueList,
  ReviewRequest,
  SeedSyntheticResult,
  SyncMailResult,
  FixtureLoadResult,
  UploadResult,
  LiteratureSplitResult,
} from './models';

@Injectable({ providedIn: 'root' })
export class QueueService {
  private readonly api = environment.apiUrl;

  constructor(private readonly http: HttpClient) {}

  list(status?: string | null): Observable<QueueList> {
    const params = status ? { status } : undefined;
    return this.http.get<QueueList>(`${this.api}/api/messages`, { params });
  }

  detail(id: string): Observable<QueueDetail> {
    return this.http.get<QueueDetail>(`${this.api}/api/messages/${id}`);
  }

  review(id: string, body: ReviewRequest): Observable<QueueDetail> {
    return this.http.post<QueueDetail>(`${this.api}/api/messages/${id}/reviews`, body);
  }

  pages(messageId: string, attachmentId: string): Observable<PdfPages> {
    return this.http.get<PdfPages>(
      `${this.api}/api/messages/${messageId}/attachments/${attachmentId}/pages`,
    );
  }

  file(messageId: string, attachmentId: string): Observable<Blob> {
    return this.http.get(`${this.api}/api/messages/${messageId}/attachments/${attachmentId}/file`, {
      responseType: 'blob',
    });
  }

  syncMail(): Observable<SyncMailResult> {
    return this.http.post<SyncMailResult>(`${this.api}/api/gmail/sync`, {});
  }

  seedSynthetic(): Observable<SeedSyntheticResult> {
    return this.http.post<SeedSyntheticResult>(`${this.api}/api/gmail/seed`, {});
  }

  loadFixtures(): Observable<FixtureLoadResult> {
    return this.http.post<FixtureLoadResult>(`${this.api}/api/fixtures/load`, {});
  }

  uploadPdfs(files: File[], subject?: string, note?: string): Observable<UploadResult> {
    const body = new FormData();
    for (const file of files) {
      body.append('files', file, file.name);
    }
    if (subject) {
      body.append('subject', subject);
    }
    if (note) {
      body.append('note', note);
    }
    return this.http.post<UploadResult>(`${this.api}/api/uploads`, body);
  }

  screenLiterature(id: string): Observable<{ ok: boolean; message: string }> {
    return this.http.post<{ ok: boolean; message: string }>(
      `${this.api}/api/messages/${id}/literature/screen`,
      {},
    );
  }

  answerLiterature(id: string, identifiable: boolean): Observable<QueueDetail> {
    return this.http.post<QueueDetail>(`${this.api}/api/messages/${id}/literature/answer`, {
      identifiable,
    });
  }

  splitLiterature(id: string): Observable<LiteratureSplitResult> {
    return this.http.post<LiteratureSplitResult>(`${this.api}/api/messages/${id}/literature/split`, {});
  }
}
