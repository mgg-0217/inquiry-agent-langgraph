import http from './http'
import type { CustomerDetail, CustomerItem, FactItem } from '../types'

export function fetchCustomers(params: {
  q?: string
  page?: number
  page_size?: number
}): Promise<{ items: CustomerItem[]; total: number; page: number; page_size: number }> {
  return http.get('/customers', { params }) as unknown as Promise<{
    items: CustomerItem[]
    total: number
    page: number
    page_size: number
  }>
}

export function fetchCustomer(id: string): Promise<CustomerDetail> {
  return http.get(`/customers/${id}`) as unknown as Promise<CustomerDetail>
}

export function fetchMemory(id: string): Promise<{
  customer: { id: string; name: string; email: string }
  facts: FactItem[]
  recent: { summary: string; outcome: string; lost_reason: string | null; evidence: string }[]
  block: string
}> {
  return http.get(`/customers/${id}/memory`) as unknown as Promise<{
    customer: { id: string; name: string; email: string }
    facts: FactItem[]
    recent: { summary: string; outcome: string; lost_reason: string | null; evidence: string }[]
    block: string
  }>
}

export function correctFact(
  customerId: string,
  factId: string,
  payload: { action: 'invalidate' | 'update'; value?: string },
): Promise<{ fact_id: string; action: string }> {
  return http.patch(`/customers/${customerId}/facts/${factId}`, payload) as unknown as Promise<{
    fact_id: string
    action: string
  }>
}
