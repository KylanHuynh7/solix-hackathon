import { useEffect, useState } from 'react'
import { customerName, getCase, supplierName } from '../api'
import { FieldStatusBadge, StateBadge } from '../components/Badges'
import { EmailPanel, type EvidenceSelection } from '../components/EmailPanel'
import { formatField } from '../format'
import type { Case, Field, Offer } from '../types/contracts'

type Kind = Parameters<typeof formatField>[1]

function FieldCell({
  field,
  label,
  kind,
  onOpen,
}: {
  field: Field
  label: string
  kind?: Kind
  onOpen: (label: string, field: Field) => void
}) {
  return (
    <button
      className={`field-cell ${field.status === 'verified' ? '' : 'field-review'}`}
      onClick={() => onOpen(label, field)}
      data-reason={field.reason ?? undefined}
      title={field.reason ?? undefined}
    >
      <span className="field-value">{formatField(field, kind)}</span>
      <FieldStatusBadge field={field} />
    </button>
  )
}

function OfferRow({ offer, onOpen }: { offer: Offer; onOpen: (label: string, field: Field) => void }) {
  const cell = (label: string, field: Field, kind?: Kind) => (
    <td>
      <FieldCell field={field} label={label} kind={kind} onOpen={onOpen} />
    </td>
  )
  return (
    <tr>
      <th scope="row">
        {supplierName(offer.supplier_id)}
        <div className="muted">
          {offer.supplier_id} · round {offer.round}
        </div>
      </th>
      {cell('NDC', offer.ndc)}
      <td>
        <div className="lots">
          {offer.lots.length === 0 && <span className="muted">—</span>}
          {offer.lots.map((lot, i) => (
            <FieldCell key={i} field={lot} label={`lot ${i + 1}`} onOpen={onOpen} />
          ))}
        </div>
      </td>
      {cell('expiry', offer.expiry)}
      {cell('quantity', offer.quantity, 'quantity')}
      {cell('unit price', offer.unit_price, 'price')}
      {cell('lead time', offer.lead_time_days, 'days')}
      {cell('storage', offer.storage)}
    </tr>
  )
}

export function CaseDetail({ caseId, onBack }: { caseId: string; onBack: () => void }) {
  const [data, setData] = useState<Case | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selection, setSelection] = useState<EvidenceSelection | null>(null)

  useEffect(() => {
    getCase(caseId).then(setData, (e: Error) => setError(e.message))
  }, [caseId])

  if (error) return <p className="warning">Could not load {caseId}: {error}</p>
  if (!data) return <p className="muted">Loading {caseId}…</p>

  const { line_item: item, requirement: req } = data

  return (
    <>
      <button className="button-ghost back" onClick={onBack}>
        ← All cases
      </button>

      <section className="card">
        <div className="title-row">
          <h2>
            {data.case_id} · {item.product}
          </h2>
          <StateBadge state={data.state} />
        </div>
        <dl className="summary">
          <div>
            <dt>Customer</dt>
            <dd>{customerName(req.customer_id)}</dd>
          </div>
          <div>
            <dt>Requested</dt>
            <dd>
              {item.quantity.toLocaleString('en-US')} {item.unit}s
              <div className="muted mono">NDC {item.requested_ndc}</div>
            </dd>
          </div>
          <div>
            <dt>Dosage form</dt>
            <dd>{req.dosage_form}</dd>
          </div>
          <div>
            <dt>Minimum expiry</dt>
            <dd>{req.min_expiry}</dd>
          </div>
          <div>
            <dt>Lots</dt>
            <dd>{req.single_lot ? 'Single lot required' : 'Multiple lots allowed'}</dd>
          </div>
          <div>
            <dt>Storage</dt>
            <dd>{req.storage_range}</dd>
          </div>
        </dl>
      </section>

      {data.exceptions.length > 0 && (
        <section className="exceptions-strip">
          <h2>
            Exceptions <span className="count">{data.exceptions.length}</span>
          </h2>
          <ul>
            {data.exceptions.map((text, i) => (
              <li key={i}>
                <span>{text}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h2>Offers</h2>
        {data.offers.length === 0 ? (
          <p className="muted">No supplier offers yet.</p>
        ) : (
          <>
            <p className="muted hint">Click any value to see the email it came from.</p>
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
                      onOpen={(label, field) =>
                        setSelection({ messageId: offer.source_message_id, label, field })
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      {selection && <EmailPanel selection={selection} onClose={() => setSelection(null)} />}
    </>
  )
}
