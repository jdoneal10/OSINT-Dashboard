/** Month helpers on 'YYYY-MM' / 'YYYY-MM-DD' strings (UTC, no Date timezone pitfalls). */

export type Month = `${number}-${string}`

export function toMonth(date: string): Month {
  return date.slice(0, 7) as Month
}

export function monthIndex(m: string): number {
  const [y, mo] = m.split('-').map(Number)
  return y * 12 + (mo - 1)
}

export function fromIndex(i: number): Month {
  const y = Math.floor(i / 12)
  const mo = (i % 12) + 1
  return `${y}-${String(mo).padStart(2, '0')}` as Month
}

/** Inclusive list of months between two 'YYYY-MM' values. */
export function monthsBetween(start: string, end: string): Month[] {
  const out: Month[] = []
  for (let i = monthIndex(start); i <= monthIndex(end); i++) out.push(fromIndex(i))
  return out
}

export function firstDay(m: string): string {
  return `${toMonth(m)}-01`
}

export function lastDay(m: string): string {
  const [y, mo] = toMonth(m).split('-').map(Number)
  const days = new Date(Date.UTC(y, mo, 0)).getUTCDate()
  return `${toMonth(m)}-${String(days).padStart(2, '0')}`
}

const NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function monthLabel(m: string): string {
  const [y, mo] = toMonth(m).split('-').map(Number)
  return `${NAMES[mo - 1]} ${y}`
}
