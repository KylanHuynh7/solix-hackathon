import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

// --- refresh: every view reloads when an action anywhere bumps the version -------------------

const RefreshContext = createContext<{ version: number; refresh: () => void }>({
  version: 0,
  refresh: () => {},
})

export const useRefresh = () => useContext(RefreshContext)

// Load data and reload on refresh(). Returns [data, error].
export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []): [T | null, string | null] {
  const { version } = useRefresh()
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    load().then(
      (value) => {
        if (!live) return
        setData(value)
        setError(null)
      },
      (e: Error) => live && setError(e.message),
    )
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, ...deps])
  return [data, error]
}

// --- approver: asked once, remembered for the browser session --------------------------------

const APPROVER_KEY = 'neurobiz.approver'

function readApprover(): string {
  try {
    return sessionStorage.getItem(APPROVER_KEY) ?? ''
  } catch {
    return ''
  }
}

const ApproverContext = createContext<{
  approver: string
  requestApprover: () => Promise<string | null>
  clearApprover: () => void
}>({ approver: '', requestApprover: async () => null, clearApprover: () => {} })

export const useApprover = () => useContext(ApproverContext)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [version, setVersion] = useState(0)
  const refresh = useCallback(() => setVersion((v) => v + 1), [])
  const [approver, setApprover] = useState(readApprover)
  const [asking, setAsking] = useState(false)
  const pending = useRef<((name: string | null) => void) | null>(null)

  const requestApprover = useCallback(() => {
    if (approver) return Promise.resolve(approver)
    setAsking(true)
    return new Promise<string | null>((resolve) => (pending.current = resolve))
  }, [approver])

  const finish = (name: string | null) => {
    if (name) {
      setApprover(name)
      try {
        sessionStorage.setItem(APPROVER_KEY, name)
      } catch {
        /* session-only convenience */
      }
    }
    setAsking(false)
    pending.current?.(name)
    pending.current = null
  }

  const clearApprover = useCallback(() => {
    setApprover('')
    try {
      sessionStorage.removeItem(APPROVER_KEY)
    } catch {
      /* ignore */
    }
  }, [])

  return (
    <RefreshContext.Provider value={{ version, refresh }}>
      <ApproverContext.Provider value={{ approver, requestApprover, clearApprover }}>
        {children}
        {asking && <ApproverModal onDone={finish} />}
      </ApproverContext.Provider>
    </RefreshContext.Provider>
  )
}

function ApproverModal({ onDone }: { onDone: (name: string | null) => void }) {
  const [name, setName] = useState('')
  return (
    <div className="drawer-backdrop modal-backdrop" onClick={() => onDone(null)}>
      <form
        className="modal"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) onDone(name.trim())
        }}
      >
        <div className="eyebrow">Human approval</div>
        <h2>Who is approving?</h2>
        <p className="muted">
          Your name is recorded in the audit ledger with every approval in this session.
        </p>
        <input
          autoFocus
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Jamie Park"
          aria-label="Approver name"
        />
        <div className="actions">
          <button type="button" className="button-ghost" onClick={() => onDone(null)}>
            Cancel
          </button>
          <button type="submit" className="button-primary" disabled={!name.trim()}>
            Continue
          </button>
        </div>
      </form>
    </div>
  )
}
