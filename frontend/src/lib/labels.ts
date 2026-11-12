import type { LabelRecord, Verdict } from '../api/types'

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
    'border_threat',
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

/**
 * Relevance labels are stored as a judgment of the pipeline's decision ("correct" /
 * "incorrect"), but the analyst answers a plain question: is the article relevant?
 * These two helpers convert between the answer and the stored verdict.
 */
export function relevanceVerdict(relevant: boolean, pipelineRelevant: boolean): Verdict {
  return relevant === pipelineRelevant ? 'correct' : 'incorrect'
}

/** The analyst's answer recorded by a relevance label (null when unlabeled). */
export function relevanceAnswer(
  label: LabelRecord | undefined,
  pipelineRelevantNow: boolean,
): boolean | null {
  if (!label) return null
  const judged = label.judged_decision ? label.judged_decision === 'relevant' : pipelineRelevantNow
  return label.verdict === 'correct' ? judged : !judged
}
