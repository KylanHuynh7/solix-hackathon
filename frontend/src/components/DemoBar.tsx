import { useEffect, useRef, useState } from 'react'
import { demoProcessNext, demoReset, demoStatus, USE_FIXTURES, type DemoStatus } from '../api'
import { useRefresh } from '../session'

const LABEL: Record<string, string> = {
  s1_offer: 'Supplier One offer',
  s2_offer: 'Supplier Two offer',
  s3_offer: 'Supplier Three offer',
  s1_injection: 'Supplier One follow-up',
  cust_yes: 'Customer confirmation',
}

const label = (key: string) => LABEL[key] ?? key
const POLL_MS = 1000

export function DemoBar() {
  const { version, refresh } = useRefresh()
  const [status, setStatus] = useState<DemoStatus | null>(null)
  const [busy, setBusy] = useState<null | 'next' | 'reset'>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const wasProcessing = useRef(false)

  // Load on every refresh; while a job runs, poll and refresh all views when it finishes.
  useEffect(() => {
    let live = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      try {
        const s = await demoStatus()
        if (!live) return
        setStatus(s)
        if (s.processing) {
          wasProcessing.current = true
          setElapsed((e) => e + POLL_MS / 1000)
          timer = setTimeout(tick, POLL_MS)
        } else if (wasProcessing.current) {
          wasProcessing.current = false
          setElapsed(0)
          const last = s.last
          setMessage(
            last?.ok
              ? `Processed: ${label(last.key)}${last.seconds && last.seconds >= 1 ? ` (${last.seconds}s)` : ''}`
              : `Failed: ${last ? label(last.key) : ''} — ${last?.error ?? 'unknown error'}`,
          )
          refresh()
        }
      } catch (e) {
        if (live) setMessage((e as Error).message)
      }
    }
    tick()
    return () => {
      live = false
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version])

  const act = async (kind: 'next' | 'reset') => {
    setBusy(kind)
    setMessage(null)
    try {
      if (kind === 'next') {
        await demoProcessNext()
        setElapsed(0)
        // A replayed job can finish before the first poll; still report it and refresh views.
        wasProcessing.current = true
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

  const processing = status?.processing
  const next = status?.next
  let text: string
  if (USE_FIXTURES) text = 'Fixture mode: processing needs the live API'
  else if (processing) text = `Agents working on: ${label(processing)}… ${Math.round(elapsed)}s`
  else if (next) text = `Next email: ${label(next)} (${(status?.index ?? 0) + 1}/${status?.total})`
  else text = status ? 'All seeded emails processed' : 'Connecting…'

  return (
    <div className="demo-bar">
      <span className="eyebrow">Demo</span>
      <span className={`demo-next ${processing ? 'demo-processing' : ''}`}>{text}</span>
      {message && !processing && <span className="demo-message">{message}</span>}
      <span className="spacer" />
      <button
        className="button-ghost"
        onClick={() => act('reset')}
        disabled={busy !== null || Boolean(processing)}
      >
        {busy === 'reset' ? 'Resetting…' : 'Reset demo'}
      </button>
      <button
        className="button-primary"
        onClick={() => act('next')}
        disabled={busy !== null || USE_FIXTURES || !next || Boolean(processing)}
      >
        {processing ? 'Processing…' : 'Process next email'}
      </button>
    </div>
  )
}
