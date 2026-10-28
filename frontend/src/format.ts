import type { Field } from './types/contracts'

function unitLabel(unit: string, n: number): string {
  const label = unit.replace(/_/g, ' ')
  if (n === 1 || label.endsWith('s')) return label
  return `${label}s`
}

// Human-readable value for a Field; the unit is shown as stated, never converted.
export function formatField(field: Field, kind?: 'price' | 'quantity' | 'days'): string {
  const value = field.value as unknown
  if (value === null || value === undefined || value === '') return '—'
  if (kind === 'price' && typeof value === 'number') {
    const [currency, basis] = (field.unit ?? '').split('/')
    const amount = value.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
    return basis ? `${currency} ${amount} / ${basis}` : `${amount} ${field.unit ?? ''}`.trim()
  }
  if ((kind === 'quantity' || kind === 'days') && typeof value === 'number') {
    const unit = field.unit ?? (kind === 'days' ? 'day' : '')
    return `${value.toLocaleString('en-US')} ${unitLabel(unit, value)}`.trim()
  }
  return String(value)
}
