export interface CustomerBrief {
  id: string
  name: string
  email: string
  country: string | null
}

export interface InboxItem {
  thread_id: string
  subject: string
  status: string
  customer: CustomerBrief | null
  message_count: number
  last_message_at: string | null
  last_from: string | null
  last_snippet: string
  created_at: string | null
}

export interface Kpis {
  today_inbound: number
  active_threads: number
  waiting_approval: number
  avg_first_response_seconds: number | null
}

export interface InboxResponse {
  items: InboxItem[]
  total: number
  page: number
  page_size: number
  kpis: Kpis
}

export interface Attachment {
  filename: string
  content_type: string
  size: number
  content_id?: string | null
}

export interface MailMessage {
  id: string
  message_id: string
  direction: string
  subject: string
  from_email: string
  from_name: string
  to_emails: string[]
  cc_emails: string[]
  body_text: string
  body_html: string
  attachments: Attachment[]
  in_reply_to: string | null
  references: string[]
  received_at: string | null
}

export interface ThreadDetail {
  thread: {
    id: string
    subject: string
    status: string
    created_at: string | null
    last_message_at: string | null
  }
  customer: CustomerBrief | null
  messages: MailMessage[]
}

export interface SyncReport {
  fetched: number
  created: number
  duplicated: number
  errors: string[]
}

export interface TraceStep {
  node: string
  status: string
  summary: string
  started_at: string | null
  duration_ms: number
  tool_calls?: { tool: string; args?: unknown; ok?: boolean; result?: unknown }[]
}

export interface QuoteInfo {
  sku: string
  qty: number
  unit_price: number
  total: number
  currency: string
  incoterm: string
  destination: string
  valid_until: string | null
  floor_price: number
  target_matched_price: number | null
  tiers: { min_qty: number; max_qty: number | null; unit_price: number }[]
}

export interface StrategyInfo {
  stance: string
  mention_history: boolean
  price_adjustment: string
  key_points: string[]
  rationale: string
}

export interface VerdictInfo {
  result: string
  score: number
  hits: { list_name: string; entry_no: string; name: string; score: number; evidence: string }[]
  rules_hit: string[]
  reasons: string[]
  evidence: string[]
}

export interface DecisionInfo {
  action: string
  reason: string
  confidence: number
}

export interface TraceResult {
  thread_id: string
  status: string
  subject: string
  pending: string[]
  steps: TraceStep[]
  memory_block: string
  decision: DecisionInfo | null
  approval: { action: string; comment: string; edited_reply: string | null; approver: string } | null
  quote: QuoteInfo | null
  strategy: StrategyInfo | null
  verdict: VerdictInfo | null
  triage: { is_spam: boolean; complete: boolean; missing: string[]; is_negotiation: boolean } | null
  reply_draft: string | null
  fact_check_ok: boolean | null
  customer: CustomerBrief | null
}

export interface CustomerItem {
  id: string
  name: string
  email: string
  country: string | null
  is_new: boolean
  thread_count: number
  created_at: string | null
}

export interface FactItem {
  id: string
  key: string
  value: string
  confidence: number
  evidence: string
  valid_until: string | null
  superseded_by: string | null
  created_at: string | null
}

export interface CustomerDetail {
  customer: CustomerItem & { domain: string | null }
  facts: FactItem[]
  interactions: {
    id: string
    summary: string
    outcome: string
    lost_reason: string | null
    evidence: string
    created_at: string | null
  }[]
  threads: { id: string; subject: string; status: string; last_message_at: string | null }[]
}
