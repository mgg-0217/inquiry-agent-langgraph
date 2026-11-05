import http from './http'

export interface SimulateSummary {
  thread_id: string
  status: string
  pending: boolean
  customer_id: string | null
  triage: Record<string, unknown> | null
  quote: Record<string, unknown> | null
  verdict: Record<string, unknown> | null
  decision: { action: string; reason: string } | null
  reply_draft: string | null
  trace: { node: string; summary: string }[]
}

export function simulateInbound(scenario: string): Promise<SimulateSummary> {
  return http.post('/simulate/inbound', { scenario }) as unknown as Promise<SimulateSummary>
}

export function simulateReply(
  threadId: string,
  body: string,
): Promise<SimulateSummary> {
  return http.post('/simulate/reply', { thread_id: threadId, body }) as unknown as Promise<SimulateSummary>
}
