import { customerName, listCases } from '../api'
import { StateBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { useLoad } from '../session'

export function CaseList({ onOpen }: { onOpen: (caseId: string) => void }) {
  const [cases, error] = useLoad(listCases)

  if (error) return <p className="notice notice-danger">Could not load cases: {error}</p>
  if (!cases) return <p className="muted">Loading cases…</p>

  return (
    <section className="panel">
      <header className="panel-head">
        <h2>
          All cases <span className="count">{cases.length}</span>
        </h2>
        <span className="muted small">Open a case to see offers, evidence and SAP documents.</span>
      </header>

      {cases.length === 0 ? (
        <p className="empty">No cases yet. Reset the demo to load the seeded case.</p>
      ) : (
        <div className="table-scroll">
          <table className="table cases">
            <thead>
              <tr>
                <th>Case</th>
                <th>Product</th>
                <th>Customer</th>
                <th className="num">Quantity</th>
                <th>Requirement</th>
                <th className="num">Offers</th>
                <th className="num">Exceptions</th>
                <th>State</th>
                <th aria-label="Open" />
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.case_id} className="clickable" onClick={() => onOpen(c.case_id)}>
                  <td>
                    <button
                      className="case-id"
                      onClick={(e) => {
                        e.stopPropagation()
                        onOpen(c.case_id)
                      }}
                    >
                      {c.case_id}
                    </button>
                  </td>
                  <td>
                    <div className="strong">{c.line_item.product}</div>
                    <div className="mono muted small">NDC {c.line_item.requested_ndc}</div>
                  </td>
                  <td>{customerName(c.requirement.customer_id)}</td>
                  <td className="num">
                    {c.line_item.quantity.toLocaleString('en-US')} {c.line_item.unit}s
                  </td>
                  <td>
                    <div>{c.requirement.dosage_form}</div>
                    <div className="muted small">
                      Expiry ≥ {c.requirement.min_expiry} ·{' '}
                      {c.requirement.single_lot ? 'single lot' : 'multiple lots'}
                    </div>
                  </td>
                  <td className="num">{c.offers.length}</td>
                  <td className="num">
                    {c.exceptions.length > 0 ? (
                      <span className="badge badge-sm badge-danger">{c.exceptions.length}</span>
                    ) : (
                      <span className="muted">0</span>
                    )}
                  </td>
                  <td>
                    <StateBadge state={c.state} />
                  </td>
                  <td className="chev">
                    <Icon name="chevron" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
