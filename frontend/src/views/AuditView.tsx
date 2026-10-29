import { useState } from 'react'
import { listAudit, verifyAudit, type VerifyResult } from '../api'
import { Icon } from '../components/Icon'
import { useLoad } from '../session'
import type { AuditEvent } from '../types/contracts'

const TONE: Record<string, string> = {
  tool_denied: 'row-denied',
  check_failed: 'row-warn',
  draft_rejected: 'row-warn',
  email_sent: 'row-ok',
  sap_document_created: 'row-ok',
}

function shortPayload(payload: Record<string, unknown>): string {
  const text = Object.entries(payload)
    .map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(' · ')
  return text.length > 180 ? `${text.slice(0, 177)}…` : text
}

// Quote every cell; prefix formula-like values so spreadsheets don't execute them.
function csvCell(value: unknown): string {
  let text = value === null || value === undefined ? '' : String(value)
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`
  return `"${text.replace(/"/g, '""')}"`
}

function exportCsv(events: AuditEvent[]) {
  const header = ['seq', 'ts', 'case_id', 'actor', 'action', 'source', 'payload', 'model', 'prev_hash', 'hash']
  const rows = events.map((e) =>
    [e.seq, e.ts, e.case_id, e.actor, e.action, e.source, JSON.stringify(e.payload), e.model, e.prev_hash, e.hash]
      .map(csvCell)
      .join(','),
  )
  const blob = new Blob([[header.join(','), ...rows].join('\n')], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `transpharmic-audit-${new Date().toISOString().slice(0, 19).replace(/:/g, '')}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export function AuditView() {
  const [events, error] = useLoad(() => listAudit())
  const [filter, setFilter] = useState<'all' | 'humans' | 'denied'>('all')
  const [verify, setVerify] = useState<VerifyResult | null>(null)
  const [verifying, setVerifying] = useState(false)
  const [verifyError, setVerifyError] = useState<string | null>(null)

  if (error) return <p className="notice notice-danger">Could not load the ledger: {error}</p>
  if (!events) return <p className="muted">Loading ledger…</p>

  const visible = events.filter((e) =>
    filter === 'humans'
      ? e.actor.startsWith('human:')
      : filter === 'denied'
        ? e.action === 'tool_denied' || e.action === 'check_failed'
        : true,
  )

  const runVerify = async () => {
    setVerifying(true)
    setVerifyError(null)
    try {
      setVerify(await verifyAudit())
    } catch (e) {
      setVerifyError((e as Error).message)
    } finally {
      setVerifying(false)
    }
  }

  return (
    <>
      <section className="panel verify-card">
        <span className="verify-icon">
          <Icon name="link" size={22} />
        </span>
        <div className="verify-copy">
          <h2>Hash-chained ledger</h2>
          <p className="muted">
            Append-only and hash-chained: each event's hash covers the previous one, so any edit or
            deleted row breaks the chain.
          </p>
        </div>
        <div className="verify-actions">
          {verify &&
            (verify.ok ? (
              <span className="verify verify-ok"><Icon name="check" size={16} />Chain verified · {verify.count} events</span>
            ) : (
              <span className="verify verify-bad">
                <Icon name="alert" size={16} />
                Chain broken at seq {verify.first_broken_seq}
              </span>
            ))}
          {verifyError && <span className="notice notice-danger">{verifyError}</span>}
          <button className="button-primary" onClick={runVerify} disabled={verifying}>
            <Icon name="audit" size={16} />
            {verifying ? 'Verifying…' : 'Verify chain'}
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div className="tabs" role="tablist">
            {(
              [
                ['all', 'All events'],
                ['humans', 'Human actions'],
                ['denied', 'Denied & failed checks'],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={filter === key}
                className={`tab ${filter === key ? 'tab-active' : ''}`}
                onClick={() => setFilter(key)}
              >
                {label}
              </button>
            ))}
          </div>
          <button className="button-ghost" onClick={() => exportCsv(visible)}>
            <Icon name="download" size={16} />
            Export CSV ({visible.length})
          </button>
        </div>

        <div className="table-scroll">
          <table className="table audit">
            <thead>
              <tr>
                <th className="num">Seq</th>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((e) => (
                <tr key={e.seq} className={TONE[e.action] ?? ''}>
                  <td className="num mono">{e.seq}</td>
                  <td className="nowrap">{new Date(e.ts).toLocaleTimeString('en-US')}</td>
                  <td className={e.actor.startsWith('human:') ? 'actor-human' : 'actor'}>{e.actor}</td>
                  <td>
                    <span className="mono action">{e.action}</span>
                    {e.action === 'tool_denied' && (
                      <span className="badge badge-sm badge-danger">denied</span>
                    )}
                  </td>
                  <td className="payload">{shortPayload(e.payload)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}
