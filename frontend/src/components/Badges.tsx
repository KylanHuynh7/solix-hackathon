import type { CaseState, Field } from '../types/contracts'
import { Icon } from './Icon'

const STATE_TONE: Record<CaseState, string> = {
  New: 'neutral',
  Quoting: 'info',
  Exception: 'danger',
  AwaitingCustomer: 'warn',
  Confirmed: 'ok',
  Ordered: 'ok',
}

const STATE_LABEL: Record<CaseState, string> = {
  New: 'New',
  Quoting: 'Quoting',
  Exception: 'Exception',
  AwaitingCustomer: 'Awaiting customer',
  Confirmed: 'Confirmed',
  Ordered: 'Ordered',
}

export function StateBadge({ state }: { state: CaseState }) {
  return <span className={`badge badge-dot badge-${STATE_TONE[state]}`}>{STATE_LABEL[state]}</span>
}

export function FieldStatusBadge({ field }: { field: Field }) {
  const verified = field.status === 'verified'
  return (
    <span
      className={`badge badge-sm ${verified ? 'badge-ok' : 'badge-warn'}`}
      aria-label={verified ? 'verified' : 'needs review'}
    >
      <Icon name={verified ? 'check' : 'alert'} size={12} />
      {verified ? 'Verified' : 'Needs review'}
    </span>
  )
}
