/** Short local date-time, e.g. "Nov 10, 2026, 14:05". */
export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function usd(value: number, digits = 2): string {
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

/** "1,435 lb" / "—". */
export function quantity(value: number | null, unit: string | null): string {
  if (value === null) return '—'
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 3 })}${unit ? ` ${unit}` : ''}`
}

export const GEO_PRECISION: Record<number, string> = {
  1: 'locality',
  2: 'municipality / port',
  3: 'state',
}

/** "1 event", "3 events". */
export function plural(n: number, noun: string): string {
  return `${n.toLocaleString()} ${noun}${n === 1 ? '' : 's'}`
}
