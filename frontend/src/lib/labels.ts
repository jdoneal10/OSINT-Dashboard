import type { Verdict } from '../api/types'

/** Fields an analyst can mark wrong in a partly wrong record. */
export const RECORD_FIELDS: Record<'events' | 'seizures', string[]> = {
  events: [
    'event_type',
    'date',
    'location',
    'fatalities',
    'perpetrators',
    'targets',
    'description',
    'evidence',
    // Hard rule 3 (ADR 0005): someone other than a reported criminal-group leader is named.
    'person_named',
  ],
  seizures: ['substance', 'quantity', 'date', 'agency', 'location'],
}

/** Scope flag: correct extraction, but outside the area of interest (low priority). */
export const OUT_OF_AOI = 'out_of_aoi'

/** Field string for a label: wrong fields plus the scope flag, sorted, comma-separated. */
export function labelField(errors: string[], outsideAoi: boolean): string {
  return [...errors.filter((f) => f !== OUT_OF_AOI), ...(outsideAoi ? [OUT_OF_AOI] : [])]
    .sort()
    .join(',')
}

export interface LabelChange {
  verdict: Verdict
  /** Comma-separated wrong fields (partial) plus out_of_aoi; "" for the whole record. */
  field: string
  note: string | null
}
