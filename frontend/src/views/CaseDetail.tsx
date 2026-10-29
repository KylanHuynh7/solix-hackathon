import { useState, type ReactNode } from 'react'
import { customerName, getCase, supplierName } from '../api'
import { FieldStatusBadge, StateBadge } from '../components/Badges'
import { EmailPanel, type EvidenceSelection } from '../components/EmailPanel'
import { Icon } from '../components/Icon'
import { SapPanel } from '../components/SapPanel'
import { SolixExport } from '../components/SolixExport'
import { formatField } from '../format'
import { useLoad } from '../session'
import type { Field, Offer } from '../types/contracts'

type Kind = Parameters<typeof formatField>[1]

function FieldCell({
  field,
  label,
  kind,
  mono,
  onOpen,
}: {
  field: Field
  label: string
  kind?: Kind
  mono?: boolean
  onOpen: (label: string, field: Field) => void
}) {
  return (
    <button
      className={`field-cell ${field.status === 'verified' ? '' : 'field-review'}`}
      onClick={() => onOpen(label, field)}
      data-reason={field.reason ?? undefined}
      title={field.reason ?? `Show the email sentence for ${label}`}
    >
      <span className={`field-value ${mono ? 'mono' : ''}`}>{formatField(field, kind)}</span>
      <FieldStatusBadge field={field} />
    </button>
  )
}

function OfferRow({
  offer,
  issues,
  onOpen,
}: {
  offer: Offer
  issues: number
  onOpen: (label: string, field: Field) => void
}) {
  const cell = (label: string, field: Field, kind?: Kind, mono?: boolean) => (
    <td>
      <FieldCell field={field} label={label} kind={kind} mono={mono} onOpen={onOpen} />
    </td>
  )
  return (
    <tr>
      <th scope="row">
        <div className="supplier">{supplierName(offer.supplier_id)}</div>
        <div className="muted small mono">
          {offer.supplier_id} · round {offer.round}
        </div>
        <div className="offer-checks">
          {issues > 0 ? (
            <span className="badge badge-sm badge-danger">
              <Icon name="alert" size={12} />
              {issues} {issues === 1 ? 'issue' : 'issues'}
            </span>
          ) : (
            <span className="badge badge-sm badge-ok">
              <Icon name="check" size={12} />
              All checks passed
            </span>
          )}
        </div>
      </th>
      {cell('NDC', offer.ndc, undefined, true)}
      <td>
        <div className="lots">
          {offer.lots.length === 0 && <span className="muted">—</span>}
          {offer.lots.map((lot, i) => (
            <FieldCell key={i} field={lot} label={`lot ${i + 1}`} mono onOpen={onOpen} />
          ))}
        </div>
      </td>
      {cell('expiry', offer.expiry, undefined, true)}
      {cell('quantity', offer.quantity, 'quantity')}
      {cell('unit price', offer.unit_price, 'price')}
      {cell('lead time', offer.lead_time_days, 'days')}
      {cell('storage', offer.storage)}
    </tr>
  )
}

export function CaseDetail({ caseId }: { caseId: string }) {
  const [data, error] = useLoad(() => getCase(caseId), [caseId])
  const [selection, setSelection] = useState<EvidenceSelection | null>(null)

  if (error) return <p className="notice notice-danger">Could not load {caseId}: {error}</p>
  if (!data) return <p className="muted">Loading {caseId}…</p>

  const { line_item: item, requirement: req } = data
  const issuesFor = (supplierId: string) =>
    data.exceptions.filter((text) => text.includes(`(${supplierId})`)).length

  const specs: [string, ReactNode][] = [
    ['Customer', customerName(req.customer_id)],
    [
      'Requested',
      <>
        {item.quantity.toLocaleString('en-US')} {item.unit}s
        <div className="mono muted small">NDC {item.requested_ndc}</div>
      </>,
    ],
    ['Dosage form', req.dosage_form],
    ['Minimum expiry', <span className="mono">{req.min_expiry}</span>],
    ['Lots', req.single_lot ? 'Single lot required' : 'Multiple lots allowed'],
    ['Storage', req.storage_range],
  ]

  return (
    <>
      <section className="panel case-hero">
        <div className="case-hero-top">
          <div>
            <div className="eyebrow">Sourcing request · {data.case_id}</div>
            <h2 className="case-title">{item.product}</h2>
          </div>
          <StateBadge state={data.state} />
        </div>
        <dl className="spec-grid">
          {specs.map(([label, value]) => (
            <div className="spec" key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </section>

      {data.exceptions.length > 0 && (
        <section className="panel alerts" aria-label="Validation exceptions">
          <header className="panel-head">
            <h2>
              <Icon name="alert" className="tone-danger" />
              Validation exceptions <span className="count count-danger">{data.exceptions.length}</span>
            </h2>
            <span className="muted small">Raised by deterministic checks, not by the model.</span>
          </header>
          <ul className="alert-list">
            {data.exceptions.map((text, i) => (
              <li key={i}>{text}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="panel">
        <header className="panel-head">
          <h2>
            Supplier offers <span className="count">{data.offers.length}</span>
          </h2>
          {data.offers.length > 0 && (
            <span className="muted small">Click any value to open the sentence it came from.</span>
          )}
        </header>
        {data.offers.length === 0 ? (
          <p className="empty">No supplier offers yet. Process the next email from the demo bar.</p>
        ) : (
          <div className="table-scroll">
            <table className="table offers">
              <thead>
                <tr>
                  <th>Supplier</th>
                  <th>NDC</th>
                  <th>Lots</th>
                  <th>Expiry</th>
                  <th>Quantity</th>
                  <th>Unit price</th>
                  <th>Lead time</th>
                  <th>Storage</th>
                </tr>
              </thead>
              <tbody>
                {data.offers.map((offer) => (
                  <OfferRow
                    key={`${offer.supplier_id}-${offer.round}`}
                    offer={offer}
                    issues={issuesFor(offer.supplier_id)}
                    onOpen={(label, field) =>
                      setSelection({ messageId: offer.source_message_id, label, field })
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <SapPanel caseId={data.case_id} />

      <SolixExport caseId={data.case_id} closed={data.state === 'Ordered'} />

      {selection && <EmailPanel selection={selection} onClose={() => setSelection(null)} />}
    </>
  )
}
