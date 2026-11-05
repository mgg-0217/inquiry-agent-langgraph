export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fmtDay(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function fmtMoney(value: number | null | undefined, currency = 'USD'): string {
  if (value === null || value === undefined) return '—'
  return `${currency} ${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}`
}

export const STATUS_LABEL: Record<string, string> = {
  received: '待处理',
  triaging: '分诊中',
  waiting_clarify: '待补充',
  processing: '处理中',
  waiting_approval: '待审批',
  replied: '已回复',
  archived_spam: '已拦截 · 垃圾',
  archived_compliance: '已拦截 · 合规',
  archived_rejected: '已拒绝',
}

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status
}

export function statusClass(status: string): string {
  if (status === 'replied') return 'b-ok'
  if (status === 'waiting_approval' || status === 'waiting_clarify') return 'b-warn'
  if (status === 'archived_compliance') return 'b-red'
  if (status.startsWith('archived')) return 'b-gray'
  return 'b-info'
}
