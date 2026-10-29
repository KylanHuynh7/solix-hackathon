import { useEffect, useState } from 'react'
import { getEmail } from '../api'
import type { Email, Field } from '../types/contracts'
import { HighlightedText } from './Highlight'
import { Icon } from './Icon'

export interface EvidenceSelection {
  messageId: string
  label: string
  field: Field
}

export function EmailPanel({
  selection,
  onClose,
}: {
  selection: EvidenceSelection
  onClose: () => void
}) {
  const [email, setEmail] = useState<Email | null | undefined>(undefined)
  const { field } = selection
  const evidence = field.evidence ?? null

  useEffect(() => {
    let live = true
    getEmail(selection.messageId).then((e) => live && setEmail(e ?? null))
    return () => {
      live = false
    }
  }, [selection.messageId])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const found = email && evidence ? email.body.includes(evidence) : false

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-label="Source email"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="drawer-header">
          <div>
            <div className="eyebrow">Source for {selection.label}</div>
            <h2>{email?.subject ?? 'Source email'}</h2>
          </div>
          <button className="button-ghost icon-button" onClick={onClose} aria-label="Close">
            <Icon name="close" />
          </button>
        </header>

        <div className={`evidence-box ${field.status === 'verified' ? '' : 'evidence-review'}`}>
          <div className="evidence-label">
            <Icon name="link" size={15} />
            Evidence quoted by the model
          </div>
          {evidence ? <code className="evidence-quote">{evidence}</code> : <span className="muted">None</span>}
          {field.reason && <div className="muted small">{field.reason}</div>}
          {email && evidence && !found && (
            <div className="notice notice-danger">
              Evidence text not found in this email. Treat this value as unverified.
            </div>
          )}
        </div>

        {email === undefined && <p className="muted">Loading…</p>}
        {email === null && <p className="notice notice-danger">Email {selection.messageId} not found.</p>}
        {email && (
          <>
            <dl className="email-meta">
              <dt>From</dt>
              <dd>{email.sender}</dd>
              <dt>To</dt>
              <dd>{email.to.join(', ')}</dd>
              <dt>Date</dt>
              <dd>{new Date(email.date).toLocaleString('en-US')}</dd>
            </dl>
            <HighlightedText text={email.body} evidence={evidence} />
          </>
        )}
      </aside>
    </div>
  )
}
