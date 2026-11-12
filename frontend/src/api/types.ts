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
export type LabelTarget = 'events' | 'seizures' | 'documents'

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
}

export interface LabelQueue {
  size: number
  done: number
  items: LabelQueueItem[]
}
