import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from './environment';
import {
  QueueDetail,
  QueueList,
  SeedSyntheticResult,
  SyncMailResult,
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

  syncMail(): Observable<SyncMailResult> {
    return this.http.post<SyncMailResult>(`${this.api}/api/gmail/sync`, {});
  }

  seedSynthetic(): Observable<SeedSyntheticResult> {
    return this.http.post<SeedSyntheticResult>(`${this.api}/api/gmail/seed`, {});
  }
}
