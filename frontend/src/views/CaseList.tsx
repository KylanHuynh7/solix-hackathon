import { useEffect, useState } from 'react'
import { listCases } from '../api'
import { StateBadge } from '../components/Badges'
import type { Case } from '../types/contracts'

export function CaseList({ onOpen }: { onOpen: (caseId: string) => void }) {
  const [cases, setCases] = useState<Case[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listCases().then(setCases, (e: Error) => setError(e.message))
  }, [])

  if (error) return <p className="warning">Could not load cases: {error}</p>
  if (!cases) return <p className="muted">Loading cases…</p>

  const exceptions = cases.flatMap((c) => c.exceptions.map((text) => ({ caseId: c.case_id, text })))

  return (
    <>
      <section className="exceptions-strip" aria-label="Open exceptions">
        <h2>
          Exceptions <span className="count">{exceptions.length}</span>
        </h2>
        {exceptions.length === 0 ? (
          <p className="muted">No open exceptions.</p>
        ) : (
          <ul>
            {exceptions.map((x, i) => (
              <li key={i}>
                <button className="link" onClick={() => onOpen(x.caseId)}>
                  {x.caseId}
                </button>
                <span>{x.text}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <h2>Cases</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Case</th>
              <th>Product</th>
              <th className="num">Quantity</th>
              <th>State</th>
              <th className="num">Exceptions</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => (
              <tr key={c.case_id} className="clickable" onClick={() => onOpen(c.case_id)}>
                <td>
                  <button className="link" onClick={() => onOpen(c.case_id)}>
                    {c.case_id}
                  </button>
                </td>
                <td>
                  {c.line_item.product}
                  <div className="muted mono">NDC {c.line_item.requested_ndc}</div>
                </td>
                <td className="num">
                  {c.line_item.quantity.toLocaleString('en-US')} {c.line_item.unit}s
                </td>
                <td>
                  <StateBadge state={c.state} />
                </td>
                <td className="num">
                  {c.exceptions.length > 0 ? (
                    <span className="badge badge-danger">{c.exceptions.length}</span>
                  ) : (
                    <span className="muted">0</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  )
}
