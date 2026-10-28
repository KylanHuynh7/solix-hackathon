import type { AuditEvent, Case, Draft, Email } from './types/contracts'
import {
  fixtureAudit,
  fixtureCases,
  fixtureDirectory,
  fixtureDrafts,
  fixtureEmails,
} from './fixtures'

// Default true so every view works offline. Set VITE_USE_FIXTURES=false to use the live API.
export const USE_FIXTURES = import.meta.env.VITE_USE_FIXTURES !== 'false'
export const API_BASE = 'http://127.0.0.1:8000'

// GET /drafts?status=rejected adds these; the frozen DraftStatus has no "rejected".
export type ApiDraft = Omit<Draft, 'status'> & {
  status: Draft['status'] | 'rejected'
  rejected_by?: string
  reason?: string
}

export interface Directory {
  suppliers: { supplier_id: string; name: string; contacts: { name: string; email: string }[] }[]
  customers: { customer_id: string; name: string; contacts: { name: string; email: string }[] }[]
  email_to_id: Record<string, string>
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) throw new Error(`${path}: ${response.status}`)
  return (await response.json()) as T
}

export async function listCases(): Promise<Case[]> {
  return USE_FIXTURES ? fixtureCases : get('/cases')
}

export async function getCase(caseId: string): Promise<Case> {
  if (!USE_FIXTURES) return get(`/cases/${encodeURIComponent(caseId)}`)
  const found = fixtureCases.find((c) => c.case_id === caseId)
  if (!found) throw new Error(`case ${caseId} not found`)
  return found
}

export async function listDrafts(caseId?: string): Promise<ApiDraft[]> {
  if (USE_FIXTURES) return fixtureDrafts.filter((d) => !caseId || d.case_id === caseId)
  const query = caseId ? `?case_id=${encodeURIComponent(caseId)}` : ''
  const [active, rejected] = await Promise.all([
    get<ApiDraft[]>(`/drafts${query}`),
    get<ApiDraft[]>(`/drafts${query ? `${query}&` : '?'}status=rejected`),
  ])
  return [...active, ...rejected]
}

export async function listAudit(caseId?: string): Promise<AuditEvent[]> {
  if (USE_FIXTURES) return fixtureAudit.filter((e) => !caseId || e.case_id === caseId)
  return get(`/audit${caseId ? `?case_id=${encodeURIComponent(caseId)}` : ''}`)
}

// TODO(K6): the API has no email endpoint yet; seeded emails come from fixtures in both modes.
export async function getEmail(messageId: string): Promise<Email | undefined> {
  return fixtureEmails.find((e) => e.message_id === messageId)
}

// Static synthetic directory (data/seed/directory.json); same in both modes.
export const directory: Directory = fixtureDirectory

export function supplierName(supplierId: string): string {
  return directory.suppliers.find((s) => s.supplier_id === supplierId)?.name ?? supplierId
}

export function customerName(customerId: string): string {
  return directory.customers.find((c) => c.customer_id === customerId)?.name ?? customerId
}
