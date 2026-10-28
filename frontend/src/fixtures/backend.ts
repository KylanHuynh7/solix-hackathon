// FIXTURE MODE ONLY: an in-memory stand-in for the K3 API so approve/reject/verify can be
// clicked offline. Mirrors the real rules (non-empty approver, approve once) but has no real
// hash chain; verify() just reports the fixture events as intact.
import type { AuditEvent, Case } from '../types/contracts'
import type { ApiDraft, DemoStatus, OutboxEmail, SapIntent, VerifyResult } from '../api'
import {
  fixtureAudit,
  fixtureCases,
  fixtureDrafts,
  fixtureOutbox,
  fixtureSapIntents,
} from './index'

const clone = <T>(value: T): T => structuredClone(value)

let cases: Case[] = clone(fixtureCases)
let drafts: ApiDraft[] = clone(fixtureDrafts)
let audit: AuditEvent[] = clone(fixtureAudit)
let intents: SapIntent[] = clone(fixtureSapIntents)
let outbox: OutboxEmail[] = clone(fixtureOutbox)

export class FixtureError extends Error {}

function log(caseId: string, actor: string, action: string, payload: Record<string, unknown>) {
  const prev = audit[audit.length - 1]
  audit.push({
    seq: (prev?.seq ?? 0) + 1,
    ts: new Date().toISOString(),
    case_id: caseId,
    actor,
    action,
    source: 'fixture',
    payload,
    model: null,
    prompt_version: null,
    prev_hash: prev?.hash ?? '0'.repeat(64),
    hash: `fixture-${audit.length + 1}`,
  })
}

function requireName(value: string, name: string): string {
  const trimmed = value.trim()
  if (!trimmed) throw new FixtureError(`${name} must not be empty`)
  return trimmed
}

export const fixtureBackend = {
  cases: () => clone(cases),
  drafts: () => clone(drafts),
  audit: () => clone(audit),
  intents: () => clone(intents),
  outbox: () => clone(outbox),

  approveDraft(draftId: string, approverRaw: string, editedBody?: string) {
    const approver = requireName(approverRaw, 'approver')
    const draft = drafts.find((d) => d.draft_id === draftId)
    if (!draft) throw new FixtureError('draft not found')
    if (draft.status !== 'proposed') throw new FixtureError(`draft is already ${draft.status}`)
    if (editedBody !== undefined) draft.body = editedBody
    if (!draft.body.trim()) throw new FixtureError('Draft body is empty.')
    draft.status = 'sent'
    draft.approver = approver
    log(draft.case_id, `human:${approver}`, 'draft_approved', { draft_id: draftId })
    outbox.push({
      outbox_id: outbox.length + 1,
      draft_id: draftId,
      case_id: draft.case_id,
      to: draft.to,
      cc: draft.cc,
      subject: draft.subject,
      body: draft.body,
      approver,
      sent_at: new Date().toISOString(),
      via: 'simulator',
    })
    log(draft.case_id, `human:${approver}`, 'email_sent', { draft_id: draftId, via: 'simulator' })
  },

  rejectDraft(draftId: string, approverRaw: string, reasonRaw: string) {
    const approver = requireName(approverRaw, 'approver')
    const reason = requireName(reasonRaw, 'reason')
    const draft = drafts.find((d) => d.draft_id === draftId)
    if (!draft) throw new FixtureError('draft not found')
    if (draft.status !== 'proposed') throw new FixtureError(`draft is already ${draft.status}`)
    Object.assign(draft, { status: 'rejected', rejected_by: approver, reason })
    log(draft.case_id, `human:${approver}`, 'draft_rejected', { draft_id: draftId, reason })
  },

  approveIntent(intentId: string, approverRaw: string) {
    const approver = requireName(approverRaw, 'approver')
    const intent = intents.find((i) => i.intent_id === intentId)
    if (!intent) throw new FixtureError('SAP intent not found')
    if (intent.status !== 'proposed') throw new FixtureError(`SAP intent is already ${intent.status}`)
    const prefix = { rfq: 'RFQ-600000', supplier_quotation: 'QTN-700000', purchase_order: 'PO-450000' }
    const sameType = intents.filter((i) => i.doc_type === intent.doc_type && i.document_number)
    intent.status = 'executed'
    intent.approver = approver
    intent.document_number = `${prefix[intent.doc_type]}${sameType.length + 1}`
    log(intent.case_id, `human:${approver}`, 'sap_document_created', {
      intent_id: intentId,
      document_number: intent.document_number,
    })
    if (intent.doc_type === 'purchase_order') {
      const c = cases.find((x) => x.case_id === intent.case_id)
      if (c) {
        log(c.case_id, `human:${approver}`, 'case_state_changed', { from: c.state, to: 'Ordered' })
        c.state = 'Ordered'
      }
    }
  },

  verify(): VerifyResult {
    return { ok: true, first_broken_seq: null, count: audit.length, ledger_file: 'fixtures' }
  },

  demoStatus(): DemoStatus {
    return { next: null, index: 5, total: 5, order: [], processing: null, last: null }
  },

  reset() {
    cases = clone(fixtureCases)
    drafts = clone(fixtureDrafts)
    audit = clone(fixtureAudit)
    intents = clone(fixtureSapIntents)
    outbox = clone(fixtureOutbox)
  },
}
