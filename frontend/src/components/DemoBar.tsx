import { useState } from 'react'
import { demoProcessNext, demoReset, demoStatus, USE_FIXTURES } from '../api'
import { useLoad, useRefresh } from '../session'

const LABEL: Record<string, string> = {
  s1_offer: 'Supplier One offer',
  s2_offer: 'Supplier Two offer',
  s3_offer: 'Supplier Three offer',
  s1_injection: 'Supplier One follow-up',
  cust_yes: 'Customer confirmation',
}

export function DemoBar() {
  const { refresh } = useRefresh()
  const [status] = useLoad(demoStatus)
  const [busy, setBusy] = useState<null | 'next' | 'reset'>(null)
  const [message, setMessage] = useState<string | null>(null)

  const act = async (kind: 'next' | 'reset') => {
    setBusy(kind)
    setMessage(null)
    try {
      if (kind === 'next') {
        const result = await demoProcessNext()
        setMessage(`Processed: ${LABEL[result.processed] ?? result.processed}`)
      } else {
        await demoReset()
        setMessage('Demo reset: fresh case and a new ledger file.')
      }
      refresh()
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const next = status?.next
  return (
    <div className="demo-bar">
      <span className="eyebrow">Demo</span>
      <span className="demo-next">
        {USE_FIXTURES
          ? 'Fixture mode: processing needs the live API'
          : next
            ? `Next email: ${LABEL[next] ?? next} (${(status?.index ?? 0) + 1}/${status?.total})`
            : 'All seeded emails processed'}
      </span>
      {message && <span className="demo-message">{message}</span>}
      <span className="spacer" />
      <button className="button-ghost" onClick={() => act('reset')} disabled={busy !== null}>
        {busy === 'reset' ? 'Resetting…' : 'Reset demo'}
      </button>
      <button
        className="button-primary"
        onClick={() => act('next')}
        disabled={busy !== null || USE_FIXTURES || !next}
      >
        {busy === 'next' ? 'Processing…' : 'Process next email'}
      </button>
    </div>
  )
}
