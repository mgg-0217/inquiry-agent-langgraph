import http from './http'
import type { InboxResponse, SyncReport, ThreadDetail } from '../types'

export function fetchInbox(params: {
  status?: string
  q?: string
  page?: number
  page_size?: number
}): Promise<InboxResponse> {
  return http.get('/inbox', { params }) as unknown as Promise<InboxResponse>
}

export function fetchThread(id: string): Promise<ThreadDetail> {
  return http.get(`/threads/${id}`) as unknown as Promise<ThreadDetail>
}

export function syncInbox(): Promise<SyncReport> {
  return http.post('/inbox/sync') as unknown as Promise<SyncReport>
}
