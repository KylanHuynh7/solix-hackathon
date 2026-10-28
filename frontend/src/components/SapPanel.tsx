import { useState } from 'react'
import { approveSapIntent, listSapIntents, type SapIntent } from '../api'
import { useApprover, useLoad, useRefresh } from '../session'

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
    <li className="intent">
      <div>
        <strong>{LABEL[intent.doc_type]}</strong>
        <div className="muted">{summary(intent.payload)}</div>
        {error && <div className="warning">{error}</div>}
      </div>
      {intent.status === 'executed' ? (
        <div className="intent-done">
          <span className="doc-number mono">{intent.document_number}</span>
          <span className="muted">approved by {intent.approver}</span>
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

  if (error) return <p className="warning">Could not load SAP actions: {error}</p>
  if (!intents || intents.length === 0) return null

  return (
    <section className="card">
      <h2>SAP documents</h2>
      <p className="muted hint">
        Proposed by the agents; nothing is written to SAP until a human approves. (SAP is mocked.)
      </p>
      <ul className="intents">
        {intents.map((intent) => (
          <IntentRow key={intent.intent_id} intent={intent} />
        ))}
      </ul>
    </section>
  )
}
