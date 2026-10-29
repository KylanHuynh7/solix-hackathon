import { useState } from 'react'
import { getSolixBundle, USE_FIXTURES, type SolixBundle } from '../api'

function download(caseId: string, bundle: SolixBundle) {
  const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `transpharmic-solix-bundle-${caseId}-${bundle.generated_at.slice(0, 19).replace(/:/g, '')}.json`
  a.click()
  URL.revokeObjectURL(url)
}

// Read-only export of the case's evidence bundle for retention in Solix (mocked target).
export function SolixExport({ caseId, closed }: { caseId: string; closed: boolean }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [exported, setExported] = useState<SolixBundle | null>(null)

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      const bundle = await getSolixBundle(caseId)
      download(caseId, bundle)
      setExported(bundle)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const verify = exported?.ledger.verify
  return (
    <section className="card solix">
      <div>
        <h2>Solix archive</h2>
        <p className="muted hint">
          {closed
            ? 'Case closed: export its evidence bundle (emails, fields with quotes, approvals, SAP documents, verified ledger) for governed retention.'
            : 'Exports the evidence bundle so far. Normally done when the case is Ordered.'}
        </p>
        {exported && verify && (
          <p className={verify.ok ? 'solix-ok' : 'warning'}>
            {verify.ok ? '✓' : '✕'} Exported {exported.ledger.events.length} ledger events
            {verify.ok ? ' · chain verified' : ` · chain broken at seq ${verify.first_broken_seq}`}
            {' · '}
            {exported.sap_documents.length} SAP documents · sha256{' '}
            <span className="mono">{exported.integrity.bundle_sha256.slice(0, 12)}…</span>
          </p>
        )}
        {error && <p className="warning">{error}</p>}
      </div>
      <button
        className={closed ? 'button-primary' : 'button-ghost'}
        onClick={run}
        disabled={busy || USE_FIXTURES}
        title={USE_FIXTURES ? 'Needs the live API' : undefined}
      >
        {busy ? 'Exporting…' : 'Export Solix bundle'}
      </button>
    </section>
  )
}
