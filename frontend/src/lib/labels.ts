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
    // Priority-topic detail (extract-v7; ADR 0009): UxS or electricity-theft fields wrong.
    'uxs',
    'energy_theft',
    // Hard rule 3: free text names someone who must not be named (victim, bystander, ...).
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

/** Person labels (ADR 0013): accuracy of this document's claims about the person. */
export const PERSON_FIELDS = ['name', 'role', 'organization', 'alias', 'status', 'event_link']

/**
 * Hard-rule-3 safeguard violations; any one fails the Phase 3 exit criterion.
 * excluded_category: a victim, bystander, witness, uninvolved relative, journalist, minor or
 * non-complicit official was recorded. contact_detail: an address, phone, email or ID number.
 * us_nexus_missed: the text reports a U.S. nexus but the record is not flagged.
 * unsupported: a claim the source does not make.
 */
export const SAFEGUARD_FIELDS = [
  'excluded_category',
  'contact_detail',
  'us_nexus_missed',
  'unsupported',
]

export const SAFEGUARD_LABELS: Record<string, string> = {
  excluded_category: 'Should not be recorded (victim, bystander, minor…)',
  contact_detail: 'Contact or ID detail stored',
  us_nexus_missed: 'U.S. nexus not flagged',
  unsupported: 'Claim not in the source',
}
