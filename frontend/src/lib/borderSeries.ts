import type { MetricSeries, MonthCount } from '../api/types'
import { monthsBetween, toMonth } from './months'

export interface StackedSeries {
  months: string[] // 'YYYY-MM'
  series: { name: string; data: number[] }[]
}

/**
 * Pivot API points into one dense series per group over a continuous month axis.
 * Missing months become 0; groups are ordered by total (largest first).
 */
export function pivot(
  points: { month: string; group: string | null; value: number }[],
  range?: [string, string],
): StackedSeries {
  if (points.length === 0 && !range) return { months: [], series: [] }
  const months = range
    ? monthsBetween(range[0], range[1])
    : monthsBetween(
        points.reduce((a, p) => (toMonth(p.month) < a ? toMonth(p.month) : a), '9999-12'),
        points.reduce((a, p) => (toMonth(p.month) > a ? toMonth(p.month) : a), '0000-01'),
      )
  const index = new Map(months.map((m, i) => [m as string, i]))
  const groups = new Map<string, number[]>()
  for (const p of points) {
    const i = index.get(toMonth(p.month))
    if (i === undefined) continue
    const name = p.group ?? 'Total'
    let data = groups.get(name)
    if (!data) {
      data = new Array<number>(months.length).fill(0)
      groups.set(name, data)
    }
    data[i] += p.value
  }
  const series = [...groups.entries()]
    .map(([name, data]) => ({ name, data }))
    .sort((a, b) => sum(b.data) - sum(a.data))
  return { months, series }
}

export function sum(values: number[]): number {
  return values.reduce((a, b) => a + b, 0)
}

/** Monthly totals of events and fatalities across the given admin1 rows. */
export function violenceTotals(
  rows: MonthCount[],
  range: [string, string],
): { months: string[]; events: number[]; fatalities: number[] } {
  const months = monthsBetween(range[0], range[1])
  const index = new Map(months.map((m, i) => [m as string, i]))
  const events = new Array<number>(months.length).fill(0)
  const fatalities = new Array<number>(months.length).fill(0)
  for (const r of rows) {
    const i = index.get(toMonth(r.month))
    if (i === undefined) continue
    events[i] += r.events
    fatalities[i] += r.fatalities
  }
  return { months, events, fatalities }
}

export function snapshotNote(m: MetricSeries | undefined): string | null {
  if (!m || m.snapshots.length === 0) return null
  const latest = m.snapshots[m.snapshots.length - 1]
  return m.snapshots.length === 1
    ? `CBP snapshot of ${latest}`
    : `CBP snapshots ${m.snapshots[0]} to ${latest} (latest per month)`
}
