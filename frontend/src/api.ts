import type { AuditEvent, Case, Draft, Email } from './types/contracts'
import { fixtureDirectory, fixtureEmails } from './fixtures'
import { fixtureBackend } from './fixtures/backend'

// Live API by default. Set VITE_USE_FIXTURES=true to work offline on fixture data.
export const USE_FIXTURES = import.meta.env.VITE_USE_FIXTURES === 'true'
export const API_BASE = 'http://127.0.0.1:8000'

// GET /drafts?status=rejected adds these; the frozen DraftStatus has no "rejected".
export type ApiDraft = Omit<Draft, 'status'> & {
  status: Draft['status'] | 'rejected'
  rejected_by?: string
  reason?: string
}

export interface SapIntent {
  intent_id: string
  case_id: string
  doc_type: 'rfq' | 'supplier_quotation' | 'purchase_order'
  payload: Record<string, unknown>
  status: 'proposed' | 'approved' | 'executed'
  approver: string | null
  document_number: string | null
}

export interface OutboxEmail {
  outbox_id: number | null
  draft_id: string
  case_id: string
  to: string[]
  cc: string[]
  subject: string
  body: string
  approver: string
  sent_at: string
  via: string
}

export interface VerifyResult {
  ok: boolean
  first_broken_seq: number | null
  count: number
  ledger_file?: string
}

export interface DemoJob {
  key: string
  processor: string
  message_id: string
  ok: boolean
  error?: string
  seconds?: number
}

export interface DemoStatus {
  next: string | null
  index: number
  total: number
  order: string[]
  processing: string | null
  last: DemoJob | null
}

export interface Directory {
  suppliers: { supplier_id: string; name: string; contacts: { name: string; email: string }[] }[]
  customers: { customer_id: string; name: string; contacts: { name: string; email: string }[] }[]
  email_to_id: Record<string, string>
}

export class ApiError extends Error {}

function detailMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    const d = detail as { problems?: string[]; missing?: string[] }
    if (d.problems) return d.problems.join(' ')
    if (d.missing) return `Missing: ${d.missing.join(', ')}`
  }
  return JSON.stringify(detail)
}

async function request<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    let message = `${response.status}`
    try {
      message = detailMessage((await response.json()).detail)
    } catch {
      /* keep status code */
    }
    throw new ApiError(message)
  }
  return (await response.json()) as T
}

const get = <T>(path: string) => request<T>('GET', path)
const post = <T>(path: string, body: unknown = {}) => request<T>('POST', path, body)

function query(params: Record<string, string | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][]
  return entries.length ? `?${new URLSearchParams(entries)}` : ''
}

// Fixture calls run synchronously; wrap so both modes are async and throw ApiError.
async function fixture<T>(fn: () => T): Promise<T> {
  try {
    return fn()
  } catch (e) {
    throw new ApiError((e as Error).message)
  }
}

// --- cases ---------------------------------------------------------------------------------

export async function listCases(): Promise<Case[]> {
  return USE_FIXTURES ? fixture(fixtureBackend.cases) : get('/cases')
}

export async function getCase(caseId: string): Promise<Case> {
  if (!USE_FIXTURES) return get(`/cases/${encodeURIComponent(caseId)}`)
  const found = fixtureBackend.cases().find((c) => c.case_id === caseId)
  if (!found) throw new ApiError(`case ${caseId} not found`)
  return found
}

// --- drafts --------------------------------------------------------------------------------

export async function listDrafts(caseId?: string): Promise<ApiDraft[]> {
  if (USE_FIXTURES) {
    return fixtureBackend.drafts().filter((d) => !caseId || d.case_id === caseId)
  }
  const [active, rejected] = await Promise.all([
    get<ApiDraft[]>(`/drafts${query({ case_id: caseId })}`),
    get<ApiDraft[]>(`/drafts${query({ case_id: caseId, status: 'rejected' })}`),
  ])
  return [...active, ...rejected]
}

export async function approveDraft(draftId: string, approver: string, editedBody?: string) {
  if (USE_FIXTURES) {
    return fixture(() => fixtureBackend.approveDraft(draftId, approver, editedBody))
  }
  await post(`/drafts/${encodeURIComponent(draftId)}/approve`, {
    approver,
    edited_body: editedBody,
  })
}

export async function rejectDraft(draftId: string, approver: string, reason: string) {
  if (USE_FIXTURES) return fixture(() => fixtureBackend.rejectDraft(draftId, approver, reason))
  await post(`/drafts/${encodeURIComponent(draftId)}/reject`, { approver, reason })
}

export async function listOutbox(): Promise<OutboxEmail[]> {
  return USE_FIXTURES ? fixture(fixtureBackend.outbox) : get('/outbox')
}

// --- SAP intents ---------------------------------------------------------------------------

export async function listSapIntents(caseId?: string): Promise<SapIntent[]> {
  if (USE_FIXTURES) {
    return fixtureBackend.intents().filter((i) => !caseId || i.case_id === caseId)
  }
  return get(`/sap-intents${query({ case_id: caseId })}`)
}

export async function approveSapIntent(intentId: string, approver: string) {
  if (USE_FIXTURES) return fixture(() => fixtureBackend.approveIntent(intentId, approver))
  await post(`/sap-intents/${encodeURIComponent(intentId)}/approve`, { approver })
}

// --- audit ---------------------------------------------------------------------------------

export async function listAudit(caseId?: string): Promise<AuditEvent[]> {
  if (USE_FIXTURES) {
    return fixtureBackend.audit().filter((e) => !caseId || e.case_id === caseId)
  }
  return get(`/audit${query({ case_id: caseId })}`)
}

export async function verifyAudit(): Promise<VerifyResult> {
  return USE_FIXTURES ? fixture(fixtureBackend.verify) : get('/audit/verify')
}

// --- Solix archive export ------------------------------------------------------------------

// Only the parts the UI reads; the full bundle is downloaded as-is.
export interface SolixBundle {
  source_system: string
  target: string
  generated_at: string
  ledger: { events: unknown[]; verify: VerifyResult; head_hash: string | null }
  sap_documents: { document_number: string | null }[]
  integrity: { bundle_sha256: string }
  [key: string]: unknown
}

export async function getSolixBundle(caseId: string): Promise<SolixBundle> {
  if (USE_FIXTURES) throw new ApiError('The Solix export needs the live API.')
  return get(`/cases/${encodeURIComponent(caseId)}/solix-bundle`)
}

// --- demo controls -------------------------------------------------------------------------

export async function demoStatus(): Promise<DemoStatus> {
  return USE_FIXTURES ? fixture(fixtureBackend.demoStatus) : get('/demo/status')
}

export async function demoReset(): Promise<DemoStatus> {
  if (USE_FIXTURES) {
    fixtureBackend.reset()
    return fixtureBackend.demoStatus()
  }
  return post('/demo/reset')
}

// Starts a background job and returns at once; poll demoStatus() until `processing` is null.
export async function demoProcessNext(): Promise<{ processing: string; key: string }> {
  if (USE_FIXTURES) throw new ApiError('Processing emails needs the live API.')
  return post('/demo/process-next')
}

// --- emails and directory ------------------------------------------------------------------

export async function getEmail(messageId: string): Promise<Email | undefined> {
  if (USE_FIXTURES) return fixtureEmails.find((e) => e.message_id === messageId)
  const found = await get<Email[]>(`/emails${query({ message_id: messageId })}`)
  return found[0]
}

// Static synthetic directory (data/seed/directory.json); same in both modes.
export const directory: Directory = fixtureDirectory

export function supplierName(supplierId: string): string {
  return directory.suppliers.find((s) => s.supplier_id === supplierId)?.name ?? supplierId
}

export function customerName(customerId: string): string {
  return directory.customers.find((c) => c.customer_id === customerId)?.name ?? customerId
}
