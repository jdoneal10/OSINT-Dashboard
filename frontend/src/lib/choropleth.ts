import type {
  CrimeChoropleth,
  CrimeMethodology,
  MunicipalityProps,
  ReferenceCollection,
} from '../api/types'
import { fromIndex, monthIndex } from './months'

/** Sequential ramp, light = more incidents (dark basemap). */
export const CHOROPLETH_COLORS = ['#3b0764', '#6b21a8', '#a21caf', '#db2777', '#fda4af']

/** Percentiles used as class lower bounds: crime counts are heavily right-skewed, so the
 *  upper classes are narrow to separate the few very violent municipalities. */
export const BREAK_PERCENTILES = [0, 0.5, 0.75, 0.9, 0.97]

/** Class breaks (lower bounds) for the nonzero values, deduplicated and increasing. */
export function quantileBreaks(values: number[], percentiles = BREAK_PERCENTILES): number[] {
  const v = values.filter((x) => x > 0).sort((a, b) => a - b)
  if (v.length === 0) return []
  const breaks: number[] = []
  for (const p of percentiles) {
    const q = v[Math.round(p * (v.length - 1))]
    if (breaks.length === 0 || q > breaks[breaks.length - 1]) breaks.push(q)
  }
  return breaks
}

/** Municipal polygons with the value for the period as property ``v`` (0 = no reports). */
export function joinValues(
  municipalities: ReferenceCollection<MunicipalityProps>,
  data: CrimeChoropleth,
): GeoJSON.FeatureCollection {
  const values = new Map(data.items.map((i) => [i.admin2_code, i.value]))
  const features: GeoJSON.Feature[] = []
  for (const f of municipalities.features) {
    if (!f.geometry) continue
    features.push({
      type: 'Feature',
      geometry: f.geometry,
      properties: { name: f.properties.name, code: f.properties.code, v: values.get(f.id) ?? 0 },
    })
  }
  return { type: 'FeatureCollection', features }
}

/** Legend rows: "12–39", "40+"; a single-value class shows just the value. */
export function breakLabels(breaks: number[]): string[] {
  return breaks.map((b, i) => {
    if (i === breaks.length - 1) return `${b.toLocaleString()}+`
    const top = breaks[i + 1] - 1
    return top === b ? b.toLocaleString() : `${b.toLocaleString()}–${top.toLocaleString()}`
  })
}

/**
 * Month range of ``span`` months ending at ``end``, clamped to the start of the SESNSP
 * methodology that contains ``end`` (the two methodologies are not comparable).
 */
export function crimeWindow(
  end: string,
  span: number,
  meta: CrimeMethodology[],
): { start: string; end: string; clamped: boolean } {
  const method = meta.find(
    (m) => end >= m.first_month.slice(0, 7) && end <= m.last_month.slice(0, 7),
  )
  const want = monthIndex(end) - span + 1
  const floor = method ? monthIndex(method.first_month) : want
  const start = fromIndex(Math.max(want, floor))
  return { start, end, clamped: want < floor }
}
