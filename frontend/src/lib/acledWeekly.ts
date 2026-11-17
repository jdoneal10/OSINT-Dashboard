import type {
  AcledOrigin,
  AcledStateTotals,
  AcledWeekPoint,
  AreaProps,
  ReferenceCollection,
} from '../api/types'

export const ACLED_EVENT_TYPES = [
  'Battles',
  'Explosions/Remote violence',
  'Violence against civilians',
  'Riots',
  'Protests',
  'Strategic developments',
]

/** ACLED weeks run Saturday to Friday and are keyed by the Saturday (ADR 0011). */
export function weekStart(isoDate: string): string {
  const d = new Date(`${isoDate.slice(0, 10)}T00:00:00Z`)
  const back = (d.getUTCDay() + 1) % 7 // Saturday = 6 -> 0
  d.setUTCDate(d.getUTCDate() - back)
  return d.toISOString().slice(0, 10)
}

export function addDays(isoDate: string, days: number): string {
  const d = new Date(`${isoDate}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

export interface WeeklyColumns {
  weeks: string[]
  events: number[]
  fatalities: number[]
  origins: AcledOrigin[]
  /** Index of the first week taken from the aggregates, or -1. */
  firstAggregate: number
}

/**
 * Dense weekly columns from ``start`` to the last point: weeks with no ACLED record are 0,
 * and keep the origin of the source that covers them (events up to the horizon).
 */
export function weeklyColumns(
  points: AcledWeekPoint[],
  start: string,
  horizonWeekEnd: string | null,
): WeeklyColumns {
  const out: WeeklyColumns = {
    weeks: [],
    events: [],
    fatalities: [],
    origins: [],
    firstAggregate: -1,
  }
  if (points.length === 0) return out
  const byWeek = new Map(points.map((p) => [p.week, p]))
  const last = points[points.length - 1].week
  const horizonStart = horizonWeekEnd ? addDays(horizonWeekEnd, -6) : null
  for (let w = weekStart(start); w <= last; w = addDays(w, 7)) {
    const p = byWeek.get(w)
    const origin: AcledOrigin =
      p?.origin ?? (horizonStart && w > horizonStart ? 'aggregate' : 'events')
    if (origin === 'aggregate' && out.firstAggregate < 0) out.firstAggregate = out.weeks.length
    out.weeks.push(w)
    out.events.push(p?.events ?? 0)
    out.fatalities.push(p?.fatalities ?? 0)
    out.origins.push(origin)
  }
  return out
}

/** Mexican state polygons with the period's ACLED event total as property ``v``. */
export function joinStates(
  aoi: ReferenceCollection<AreaProps>,
  totals: AcledStateTotals,
): GeoJSON.FeatureCollection {
  const values = new Map(totals.items.map((i) => [i.admin1_code, i.events]))
  const features: GeoJSON.Feature[] = []
  for (const f of aoi.features) {
    if (!f.geometry || f.properties.country_iso3 !== 'MEX' || !f.properties.admin1_code) continue
    features.push({
      type: 'Feature',
      geometry: f.geometry,
      properties: {
        name: f.properties.name,
        code: f.properties.admin1_code,
        v: values.get(f.properties.admin1_code) ?? 0,
      },
    })
  }
  return { type: 'FeatureCollection', features }
}
