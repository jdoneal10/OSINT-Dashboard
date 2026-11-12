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
  role: 'actor1' | 'actor2' | 'assoc_actor1' | 'assoc_actor2' | string
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
  actors: EventActor[]
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
