import type { MetricSeries, MonthCount } from '../api/types'
import { monthsBetween, toMonth } from './months'

/** null = no data published/available for that month (drawn as a gap, never as zero). */
export type Value = number | null

export interface StackedSeries {
  months: string[] // 'YYYY-MM'
  series: { name: string; data: Value[] }[]
}

/**
 * Pivot API points into one dense series per group over a continuous month axis.
 * Inside the span the source covers, missing months are 0 (genuinely none reported);
 * outside it (not yet published, or before coverage) they are null so charts show a gap
 * instead of a misleading drop. Groups are ordered by total (largest first).
 */
export function pivot(
  points: { month: string; group: string | null; value: number }[],
  range?: [string, string],
): StackedSeries {
  if (points.length === 0) return { months: range ? monthsBetween(...range) : [], series: [] }
  const covered = points.map((p) => toMonth(p.month)).sort()
  const [first, last] = [covered[0], covered[covered.length - 1]]
  const months = range ? monthsBetween(range[0], range[1]) : monthsBetween(first, last)
  const index = new Map(months.map((m, i) => [m as string, i]))
  const blank = (): Value[] => months.map((m) => (m < first || m > last ? null : 0))
  const groups = new Map<string, Value[]>()
  for (const p of points) {
    const i = index.get(toMonth(p.month))
    if (i === undefined) continue
    const name = p.group ?? 'Total'
    let data = groups.get(name)
    if (!data) {
      data = blank()
      groups.set(name, data)
    }
    data[i] = (data[i] ?? 0) + p.value
  }
  const series = [...groups.entries()]
    .map(([name, data]) => ({ name, data }))
    .sort((a, b) => sum(b.data) - sum(a.data))
  return { months, series }
}

export function sum(values: Value[]): number {
  return values.reduce<number>((a, b) => a + (b ?? 0), 0)
}

/**
 * Monthly totals of events and fatalities across the given admin1 rows. Months after
 * ``through`` (the last date the source covers, e.g. ACLED's access-tier lag) are null.
 */
export function violenceTotals(
  rows: MonthCount[],
  range: [string, string],
  through?: string | null,
): { months: string[]; events: Value[]; fatalities: Value[] } {
  const months = monthsBetween(range[0], range[1])
  const end = through ? toMonth(through) : null
  const index = new Map(months.map((m, i) => [m as string, i]))
  const init = (): Value[] => months.map((m) => (end && m > end ? null : 0))
  const events = init()
  const fatalities = init()
  for (const r of rows) {
    const i = index.get(toMonth(r.month))
    if (i === undefined || events[i] === null) continue
    events[i] = (events[i] ?? 0) + r.events
    fatalities[i] = (fatalities[i] ?? 0) + r.fatalities
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
