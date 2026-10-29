import { useState } from 'react'
import { approveSapIntent, listSapIntents, type SapIntent } from '../api'
import { useApprover, useLoad, useRefresh } from '../session'
import { Icon } from './Icon'

const LABEL: Record<SapIntent['doc_type'], string> = {
  rfq: 'Request for quotation',
  supplier_quotation: 'Supplier quotation',
  purchase_order: 'Purchase order',
}

function summary(payload: Record<string, unknown>): string {
  const parts = [
    payload.Material && `NDC ${payload.Material}`,
    payload.Quantity &&
      `${payload.Quantity} ${payload.Unit ?? ''}${payload.Unit && Number(payload.Quantity) !== 1 ? 's' : ''}`.trim(),
    payload.Batch && `lot ${payload.Batch}`,
    payload.NetPrice && `${payload.Currency ?? ''} ${Number(payload.NetPrice).toFixed(2)} / ${payload.Unit ?? 'unit'}`,
    payload.Supplier && `supplier ${payload.Supplier}`,
  ]
  return parts.filter(Boolean).join(' · ')
}

function IntentRow({ intent }: { intent: SapIntent }) {
  const { refresh } = useRefresh()
  const { requestApprover } = useApprover()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const approve = async () => {
    const approver = await requestApprover()
    if (!approver) return
    setBusy(true)
    setError(null)
    try {
      await approveSapIntent(intent.intent_id, approver)
      refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className={`intent ${intent.status === 'executed' ? 'intent-executed' : ''}`}>
      <span className="intent-icon">
        <Icon name={intent.status === 'executed' ? 'check' : 'doc'} />
      </span>
      <div className="intent-main">
        <strong>{LABEL[intent.doc_type]}</strong>
        <div className="muted small">{summary(intent.payload)}</div>
        {error && <div className="notice notice-danger">{error}</div>}
      </div>
      {intent.status === 'executed' ? (
        <div className="intent-done">
          <span className="doc-number mono">{intent.document_number}</span>
          <span className="muted small">Approved by {intent.approver}</span>
        </div>
      ) : (
        <button className="button-primary" onClick={approve} disabled={busy}>
          {busy ? 'Creating…' : 'Approve'}
        </button>
      )}
    </li>
  )
}

export function SapPanel({ caseId }: { caseId: string }) {
  const [intents, error] = useLoad(() => listSapIntents(caseId), [caseId])

  if (error) return <p className="notice notice-danger">Could not load SAP actions: {error}</p>
  if (!intents || intents.length === 0) return null

  const pending = intents.filter((i) => i.status !== 'executed').length

  return (
    <section className="panel">
      <header className="panel-head">
        <h2>
          <Icon name="database" />
          SAP documents{' '}
          <span className="count">{pending > 0 ? `${pending} to approve` : 'all created'}</span>
        </h2>
        <span className="badge badge-neutral">SAP mock</span>
      </header>
      <p className="panel-note muted small">
        Proposed by the agents. Nothing is written to SAP until a human approves it.
      </p>
      <ul className="intents">
        {intents.map((intent) => (
          <IntentRow key={intent.intent_id} intent={intent} />
        ))}
      </ul>
    </section>
  )
}
