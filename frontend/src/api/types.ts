import type { Geometry } from 'geojson'

export interface Citation {
  title: string
  publisher: string
  url: string
  accessed: string
  note?: string | null
}

export interface Health {
  status: 'ok' | 'degraded'
  version: string
  db: 'ok' | 'error'
  postgis_version: string | null
  worker_last_heartbeat: string | null
}

export interface ReferenceFeature<P> {
  type: 'Feature'
  id: string
  geometry: Geometry | null
  properties: P
}

export interface ReferenceCollection<P> {
  type: 'FeatureCollection'
  features: ReferenceFeature<P>[]
}

export interface AreaProps {
  slug: string
  name: string
  area_type: string
  country_iso3: string
  admin1_code: string | null
  phase: number
  label_point: [number, number]
  sources: Citation[]
}

export interface NodeProps {
  slug: string
  name: string
  node_type: string
  code: string | null
  country_iso3: string | null
  admin1_code: string | null
  label_point: [number, number] | null
  attributes: Record<string, unknown>
  sources: Citation[]
}

// ---------------------------------------------------------------- Phase 1

export interface EventActor {
  id: number
  name: string
  type: string
  role: 'actor1' | 'actor2' | 'assoc_actor1' | 'assoc_actor2' | 'perpetrator' | 'target' | string
}

export interface EventDetail {
  id: number
  source: string
  source_key: string
  source_url: string | null
  retrieved_at: string
  confidence: number | null
  event_date: string
  event_type: string
  sub_event_type: string | null
  fatalities: number | null
  lon: number | null
  lat: number | null
  geo_precision: number | null
  time_precision: number | null
  admin1_code: string | null
  admin1_name: string | null
  admin2_name: string | null
  location_name: string | null
  description: string | null
  credibility: number | null
  cluster_id: number | null
  in_aoi: boolean
  /** Priority border-threat category (ADR 0007), or null. */
  border_threat: string | null
  /** Unmanned systems (extract-v7; ADR 0009): set when the event involves criminal UxS. */
  uxs_activity?: string | null
  uxs_platform?: string | null
  uxs_missions?: string[]
  uxs_payloads?: string[]
  /** Reported electricity theft (extract-v7): method, what it powered, facilitator role. */
  energy_method?: string | null
  energy_powered?: string[]
  energy_facilitator?: string | null
  /** Scale exactly as the source reports it (kW, MW, equipment count); never estimated. */
  energy_scale?: string | null
  /** Supporting quote from the source text (news-derived events only). */
  evidence: string | null
  actors: EventActor[]
  /** Documents the event was extracted from (empty for ACLED). */
  document_ids: number[]
}

/** Compact map-point properties from /events/geojson. */
export interface EventPointProps {
  id: number
  d: string
  t: string
  f: number
  gp: number | null
  a: number[]
  bt: string | null
}

export interface EventPoints {
  type: 'FeatureCollection'
  features: { type: 'Feature'; id: number; geometry: GeoJSON.Point; properties: EventPointProps }[]
  truncated: boolean
}

export interface EventsMeta {
  total: number
  min_date: string | null
  max_date: string | null
  accessed: string | null
  sources: string[]
}

export interface EventTypeCount {
  event_type: string
  events: number
}

/** Combined weekly ACLED series (ADR 0011): events up to the horizon, aggregates after. */
export type AcledOrigin = 'events' | 'aggregate'

export interface AcledWeeklyMeta {
  events_through: string | null
  horizon_week_end: string | null
  aggregate_snapshot: string | null
  aggregate_first_week: string | null
  aggregate_last_week: string | null
  events_accessed: string | null
  aggregate_accessed: string | null
}

export interface AcledWeekPoint {
  week: string
  events: number
  fatalities: number
  origin: AcledOrigin
}

export interface AcledWeeklySeries {
  meta: AcledWeeklyMeta
  points: AcledWeekPoint[]
}

export interface AcledStateTotals {
  meta: AcledWeeklyMeta
  start: string | null
  end: string | null
  origins: AcledOrigin[]
  items: { admin1_code: string; events: number; fatalities: number }[]
}

export interface MonthCount {
  month: string
  admin1_code: string | null
  events: number
  fatalities: number
}

export interface ActorSummary {
  id: number
  slug: string
  name: string
  actor_type: string
  parent_id: number | null
  aliases: string[]
  event_count: number
  designation_count: number
}

export interface SeriesPoint {
  month: string
  group: string | null
  value: number
}

export interface MetricSeries {
  metric: string
  aor: string[]
  unit: string | null
  group_by: string | null
  as_of: string | null
  snapshots: string[]
  retrieved_at: string | null
  notice: string
  series: SeriesPoint[]
}

export interface SeizureSeries {
  aor: string[]
  weight: MetricSeries
  events: MetricSeries
}

export interface Adjacency {
  sector: string
  name: string
  adjacent_admin1: string[]
  field_office: string | null
  method: string | null
  sources: Citation[]
}

// ---------------------------------------------------------------- Phase 2

export interface SourceRef {
  slug: string
  name: string
  reliability: string
}

export interface SourceCount extends SourceRef {
  documents: number
}

export interface ClusterRef {
  id: number
  reliability: string | null
  credibility: number | null
  /** Admiralty grade, e.g. "B2". */
  admiralty: string | null
  n_documents: number
  n_independent_sources: number
  has_conflicts: boolean
  /** An ACLED event is attached as corroboration (ADR 0006); show ACLED attribution. */
  acled_corroborated: boolean
}

export type PipelineStatus =
  'new' | 'filtered_out' | 'relevant' | 'batched' | 'extracted' | 'quarantined' | 'skipped'

export interface DocumentSummary {
  id: number
  title: string | null
  summary_en: string | null
  source: SourceRef
  url: string | null
  published_at: string | null
  retrieved_at: string
  language: string | null
  status: PipelineStatus
  relevance_score: number | null
  duplicate_of_id: number | null
  n_events: number
  n_seizures: number
  in_aoi: boolean
  /** Border-threat categories of the document's events (ADR 0007). */
  border_threats: string[]
  clusters: ClusterRef[]
  admiralty: string | null
}

export interface DocumentPage {
  items: DocumentSummary[]
  next_cursor: string | null
}

export interface SeizureRecord {
  id: number
  source: string
  seizure_date: string
  substance: string
  chemical_class: string | null
  quantity: number | null
  unit: string | null
  seizing_agency: string | null
  admin1_code: string | null
  node_id: number | null
  lon: number | null
  lat: number | null
  in_aoi: boolean
  /** Small drug amount or contraband (owner priority framework); hidden from the feed by default. */
  low_priority: boolean
  confidence: number | null
  credibility: number | null
  llm_model: string | null
  prompt_version: string | null
}

export interface QuarantineEntry {
  id: number
  stage: string
  model: string
  prompt_version: string
  reason: string
  error: string | null
  created_at: string
}

export type Verdict = 'correct' | 'incorrect' | 'partial'
export type LabelTarget = 'events' | 'seizures' | 'documents' | 'persons'

export interface LabelRecord {
  id: number
  document_id: number
  target_table: LabelTarget
  target_id: number
  field: string
  verdict: Verdict
  note: string | null
  prompt_version: string | null
  /** Relevance labels: the pipeline decision judged, frozen at labeling time. */
  judged_decision: 'relevant' | 'not_relevant' | null
  updated_at: string
}

export interface LabelInput {
  document_id: number
  target_table: LabelTarget
  target_id: number
  field: string
  verdict: Verdict
  note?: string | null
}

export interface DocumentDetail extends DocumentSummary {
  original_text: string | null
  feed_summary: string | null
  text_policy: string
  relevance_model: string | null
  llm_model: string | null
  prompt_version: string | null
  llm_input_tokens: number | null
  llm_output_tokens: number | null
  events: EventDetail[]
  seizures: SeizureRecord[]
  /** Persons extracted from this document, with this document's claims only (ADR 0013). */
  persons?: DocPerson[]
  quarantine: QuarantineEntry[]
  labels: LabelRecord[]
  duplicates: number[]
}

export interface Assessment {
  id: number
  judgment: string
  likelihood: string | null
  analytic_confidence: string | null
  resolved: Record<string, unknown>
  cited_document_ids: number[]
  cited_event_ids: number[]
  llm_model: string | null
  prompt_version: string | null
  created_at: string
}

export interface ClusterDetail extends ClusterRef {
  first_date: string
  last_date: string
  event_type: string
  admin1_code: string | null
  lon: number | null
  lat: number | null
  n_events: number
  confidence: number | null
  conflicts: Record<string, unknown[]>
  events: EventDetail[]
  documents: DocumentSummary[]
  assessments: Assessment[]
}

export interface DesignationRecord {
  id: number
  source: string
  source_url: string | null
  retrieved_at: string
  designation_type: string
  program: string | null
  action: string
  action_date: string
  title: string
  listed_parties: { name: string; type: string; aliases?: string[] }[]
  actors: { id: number; name: string }[]
}

export interface DesignationPage {
  items: DesignationRecord[]
  total: number
}

export interface CrimeMethodology {
  methodology: string
  snapshot_date: string
  first_month: string
  last_month: string
  crime_types: string[]
}

export interface CrimeChoropleth {
  methodology: string
  snapshot_date: string
  crime_type: string
  start: string
  end: string
  items: { admin2_code: string; admin1_code: string; name: string | null; value: number }[]
}

export interface MunicipalityProps {
  code: string
  name: string
  admin1_code: string
}

export interface LLMUsage {
  month: string
  spent_usd: number
  cap_usd: number
  pause_threshold_usd: number
  paused: boolean
  calls: number
  failed_calls: number
  quarantined: number
  by_stage: { stage: string; model: string; calls: number; cost_usd: number }[]
}

export interface LabelQueueItem {
  document_id: number
  source: string
  status: PipelineStatus
  title: string | null
  n_records: number
  n_labeled_records: number
  relevance_labeled: boolean
  done: boolean
  /** Appended so enough documents with records get labeled (record_documents). */
  top_up?: boolean
}

export interface LabelQueue {
  size: number
  done: number
  items: LabelQueueItem[]
}

/** /priority/* panels (ADR 0009): counts of reported events. */
export interface TopicMonth {
  month: string // 'YYYY-MM'
  counts: Record<string, number>
}

export interface TopicSummary {
  total: number
  sources: number
  months: TopicMonth[]
  breakdown: Record<string, Record<string, number>>
  states: Record<string, number>
  caveat: string
}

export interface LadderRow {
  rung: number
  label: string
  /** False when no extraction field can show this rung yet. */
  captured: boolean
  use: number
  capability: number
  first_seen: string | null
  last_seen: string | null
}

export interface UxsSummary extends TopicSummary {
  ladder: LadderRow[]
  ladder_note: string
}

export interface EventPage {
  items: EventDetail[]
  next_cursor: string | null
}

/** Person records (hard rule 3; ADR 0008, ADR 0013): every claim cited and graded. */
export interface PersonSummary {
  id: number
  display_name: string
  roles: string[]
  organizations: string[]
  /** Distinct outlets; outlets may reprint one another. */
  n_sources: number
  n_documents: number
  n_records: number
  last_reported_on: string | null
  us_person: boolean
  disputed: boolean
}

export interface PersonPage {
  items: PersonSummary[]
  total: number
}

export interface PersonCitation {
  source: string
  source_url: string | null
  document_id: number | null
  designation_id: number | null
  reported_on: string
  /** Admiralty reliability + credibility, e.g. "B3". */
  grade: string
  evidence: string | null
  basis: string // always "as reported"
}

export interface PersonClaim {
  kind: 'role' | 'alias' | 'nationality' | 'status' | 'title' | 'organization' | 'event'
  value: string
  record_id: number
  /** The name this claim's source published. */
  reported_name: string
  actor_id: number | null
  event_id: number | null
  event_date: string | null
  citation: PersonCitation
}

export interface PersonRecord {
  id: number
  display_name: string
  sources: string[]
  us_person: boolean
  /** Undo this to separate the record; null on the record whose name is shown. */
  merge_id: number | null
  into_id: number | null
}

export interface PersonDetail extends PersonSummary {
  dispute_note: string | null
  claims: PersonClaim[]
  records: PersonRecord[]
  distinct_from: { id: number; person_id: number; display_name: string }[]
}

export interface MergeSuggestion {
  primary_id: number
  us_person: boolean
  candidates: {
    person: PersonSummary
    sources: string[]
    aliases: string[]
    evidence: string | null
    selected: boolean
    reasons: string[]
    warning: string | null
  }[]
}

export interface MergeSuggestionList {
  items: MergeSuggestion[]
  hidden_us_persons: number
}

export interface DocPersonClaim {
  evidence?: string | null
  kind: string
  value: string
  event_id: number | null
}

export interface DocPerson {
  id: number
  display_name: string
  us_person: boolean
  disputed: boolean
  claims: DocPersonClaim[]
}
