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
