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

export interface LabelChange {
  verdict: Verdict
  /** Comma-separated wrong fields for a partial verdict; "" for the whole record. */
  field: string
  note: string | null
}
