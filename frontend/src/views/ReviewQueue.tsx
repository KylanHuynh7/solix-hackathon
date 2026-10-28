import { useState } from 'react'
import {
  approveDraft,
  directory,
  listCases,
  listDrafts,
  listOutbox,
  rejectDraft,
  type ApiDraft,
  type OutboxEmail,
} from '../api'
import { useApprover, useLoad, useRefresh } from '../session'
import type { Case } from '../types/contracts'

// Plain-English validator results that relate to this draft's recipients.
function relatedExceptions(draft: ApiDraft, cases: Case[]): string[] {
  const ids = draft.to.map((email) => directory.email_to_id[email]).filter(Boolean)
  const exceptions = cases.find((c) => c.case_id === draft.case_id)?.exceptions ?? []
  return exceptions.filter((text) => ids.some((id) => text.includes(`(${id})`)))
}

function DraftCard({ draft, cases }: { draft: ApiDraft; cases: Case[] }) {
  const { refresh } = useRefresh()
  const { requestApprover } = useApprover()
  const [body, setBody] = useState(draft.body)
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)
  const reasons = relatedExceptions(draft, cases)

  const run = async (action: (approver: string) => Promise<unknown>) => {
    const approver = await requestApprover()
    if (!approver) return
    setBusy(true)
    setError(null)
    try {
      await action(approver)
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }

  const approve = async () => {
    const edited = body !== draft.body ? body : undefined
    if (await run((approver) => approveDraft(draft.draft_id, approver, edited))) {
      setSent(true)
      setTimeout(refresh, 1200)
    }
  }

  const reject = async () => {
    if (await run((approver) => rejectDraft(draft.draft_id, approver, reason))) refresh()
  }

  return (
    <article className={`card draft ${sent ? 'draft-sent' : ''}`}>
      <header className="draft-header">
        <div>
          <span className={`badge ${draft.recipient_role === 'customer' ? 'badge-info' : 'badge-neutral'}`}>
            To {draft.recipient_role}
          </span>
          <span className="muted"> proposed by </span>
          <strong>{draft.created_by}</strong>
          <span className="muted"> · {draft.case_id}</span>
        </div>
        <span className="muted mono">{draft.draft_id}</span>
      </header>

      <dl className="email-meta">
        <dt>To</dt>
        <dd>{draft.to.join(', ')}</dd>
        {draft.cc.length > 0 && (
          <>
            <dt>Cc</dt>
            <dd>{draft.cc.join(', ')}</dd>
          </>
        )}
        <dt>Subject</dt>
        <dd>
          <strong>{draft.subject}</strong>
        </dd>
      </dl>

      <div className={`reasons ${reasons.length ? 'reasons-fail' : 'reasons-ok'}`}>
        <div className="eyebrow">Why this draft</div>
        {reasons.length ? (
          <ul>
            {reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        ) : (
          <p>No validator exceptions for this recipient; all checks on the offer passed.</p>
        )}
      </div>

      <label className="eyebrow" htmlFor={`body-${draft.draft_id}`}>
        Body {body !== draft.body && <span className="badge badge-sm badge-warn">edited</span>}
      </label>
      <textarea
        id={`body-${draft.draft_id}`}
        className="input textarea"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        disabled={busy || sent}
        rows={Math.min(16, body.split('\n').length + 1)}
      />

      {error && <p className="warning">{error}</p>}

      {sent ? (
        <p className="sent-note">✓ Sent via simulator. Recorded in the audit ledger.</p>
      ) : rejecting ? (
        <div className="reject-row">
          <input
            autoFocus
            className="input"
            placeholder="Reason for rejecting (recorded in the ledger)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <button className="button-ghost" onClick={() => setRejecting(false)} disabled={busy}>
            Cancel
          </button>
          <button className="button-danger" onClick={reject} disabled={busy || !reason.trim()}>
            Reject draft
          </button>
        </div>
      ) : (
        <div className="actions">
          <button className="button-ghost" onClick={() => setRejecting(true)} disabled={busy}>
            Reject…
          </button>
          <button className="button-primary" onClick={approve} disabled={busy}>
            {busy ? 'Sending…' : 'Approve & send'}
          </button>
        </div>
      )}
    </article>
  )
}

function SentList({ outbox }: { outbox: OutboxEmail[] }) {
  if (outbox.length === 0) return <p className="muted card">Nothing sent yet.</p>
  return (
    <>
      {[...outbox].reverse().map((email) => (
        <article key={email.draft_id} className="card draft">
          <header className="draft-header">
            <div>
              <span className="badge badge-ok">Sent via {email.via}</span>
              <span className="muted"> approved by </span>
              <strong>{email.approver}</strong>
            </div>
            <span className="muted">{new Date(email.sent_at).toLocaleString('en-US')}</span>
          </header>
          <dl className="email-meta">
            <dt>To</dt>
            <dd>{email.to.join(', ')}</dd>
            <dt>Subject</dt>
            <dd>
              <strong>{email.subject}</strong>
            </dd>
          </dl>
          <pre className="email-body">{email.body}</pre>
        </article>
      ))}
    </>
  )
}

function RejectedList({ drafts }: { drafts: ApiDraft[] }) {
  if (drafts.length === 0) return <p className="muted card">No rejected drafts.</p>
  return (
    <>
      {drafts.map((d) => (
        <article key={d.draft_id} className="card draft">
          <header className="draft-header">
            <div>
              <span className="badge badge-danger">Rejected</span>
              <span className="muted"> by </span>
              <strong>{d.rejected_by}</strong>
              <span className="muted"> · proposed by {d.created_by}</span>
            </div>
            <span className="muted mono">{d.draft_id}</span>
          </header>
          <p>
            <span className="muted">Reason: </span>
            {d.reason}
          </p>
          <dl className="email-meta">
            <dt>To</dt>
            <dd>{d.to.join(', ')}</dd>
            <dt>Subject</dt>
            <dd>{d.subject}</dd>
          </dl>
          <pre className="email-body">{d.body}</pre>
        </article>
      ))}
    </>
  )
}

type Tab = 'queue' | 'sent' | 'rejected'

export function ReviewQueue() {
  const [tab, setTab] = useState<Tab>('queue')
  const { approver, clearApprover } = useApprover()
  const [data, error] = useLoad(() => Promise.all([listDrafts(), listOutbox(), listCases()]))

  if (error) return <p className="warning">Could not load drafts: {error}</p>
  if (!data) return <p className="muted">Loading drafts…</p>

  const [drafts, outbox, cases] = data
  const proposed = drafts.filter((d) => d.status === 'proposed')
  const rejected = drafts.filter((d) => d.status === 'rejected')

  return (
    <>
      <div className="title-row">
        <div className="tabs" role="tablist">
          {(
            [
              ['queue', `Needs approval`, proposed.length],
              ['sent', 'Sent', outbox.length],
              ['rejected', 'Rejected', rejected.length],
            ] as const
          ).map(([key, label, count]) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              className={`tab ${tab === key ? 'tab-active' : ''}`}
              onClick={() => setTab(key)}
            >
              {label} <span className="count">{count}</span>
            </button>
          ))}
        </div>
        {approver && (
          <span className="muted">
            Approving as <strong>{approver}</strong>{' '}
            <button className="link" onClick={clearApprover}>
              change
            </button>
          </span>
        )}
      </div>

      {tab === 'queue' &&
        (proposed.length === 0 ? (
          <p className="muted card">No drafts waiting for approval.</p>
        ) : (
          proposed.map((d) => <DraftCard key={d.draft_id} draft={d} cases={cases} />)
        ))}
      {tab === 'sent' && <SentList outbox={outbox} />}
      {tab === 'rejected' && <RejectedList drafts={rejected} />}
    </>
  )
}
