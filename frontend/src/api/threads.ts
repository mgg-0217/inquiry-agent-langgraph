import http from './http'
import type { TraceResult } from '../types'

export function fetchTrace(id: string): Promise<TraceResult> {
  return http.get(`/threads/${id}/trace`) as unknown as Promise<TraceResult>
}

export function processThread(id: string): Promise<{
  thread_id: string
  status: string
  pending: boolean
}> {
  return http.post(`/threads/${id}/process`) as unknown as Promise<{
    thread_id: string
    status: string
    pending: boolean
  }>
}

export function closeThread(id: string): Promise<{ thread_id: string; status: string }> {
  return http.post(`/threads/${id}/close`) as unknown as Promise<{
    thread_id: string
    status: string
  }>
}

export function resumeThread(
  id: string,
  payload: {
    action: 'approve' | 'modify' | 'reject' | 'reassign'
    comment?: string
    edited_reply?: string
    approver?: string
  },
): Promise<{
  thread_id: string
  action: string
  comment: string
  sent: boolean
  pending: boolean
  reply_final: string | null
}> {
  return http.post(`/threads/${id}/resume`, payload) as unknown as Promise<{
    thread_id: string
    action: string
    comment: string
    sent: boolean
    pending: boolean
    reply_final: string | null
  }>
}

export function restoreThread(id: string): Promise<{ thread_id: string; status: string; pending: boolean }> {
  return http.post(`/threads/${id}/restore`) as unknown as Promise<{
    thread_id: string
    status: string
    pending: boolean
  }>
}
