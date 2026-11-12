import { toQuery } from '../lib/query'
import type {
  ActorSummary,
  Adjacency,
  AreaProps,
  ClusterDetail,
  CrimeChoropleth,
  CrimeMethodology,
  DesignationPage,
  DocumentDetail,
  DocumentPage,
  EventDetail,
  EventPoints,
  EventsMeta,
  EventTypeCount,
  Health,
  LabelInput,
  LabelQueue,
  LabelRecord,
  LLMUsage,
  MetricSeries,
  MunicipalityProps,
  SourceCount,
  MonthCount,
  NodeProps,
  ReferenceCollection,
  SeizureSeries,
} from './types'

/** All API calls go through the Vite dev proxy at /api → 127.0.0.1:8000. */
export const API_BASE = '/api'

export class ApiError extends Error {
  readonly status: number | null

  constructor(message: string, status: number | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, { headers: { Accept: 'application/json' }, ...init })
  } catch (err) {
    throw new ApiError(`API unreachable: ${(err as Error).message}`, null)
  }
  if (!res.ok) {
    const method = init?.method ?? 'GET'
    let detail = ''
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = `: ${body.detail}`
    } catch {
      // non-JSON error body
    }
    throw new ApiError(`${method} ${path} failed with HTTP ${res.status}${detail}`, res.status)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

function sendJson<T>(method: 'PUT' | 'DELETE', path: string, body?: unknown): Promise<T> {
  return getJson<T>(path, {
    method,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export const api = {
  health: (init?: RequestInit) => getJson<Health>('/health', init),
  aoi: (phase = 1, init?: RequestInit) =>
    getJson<ReferenceCollection<AreaProps>>(`/reference/aoi?phase=${phase}`, init),
  nodes: (init?: RequestInit) => getJson<ReferenceCollection<NodeProps>>('/reference/nodes', init),
  adjacency: (init?: RequestInit) => getJson<Adjacency[]>('/reference/adjacency', init),
  eventsMeta: (init?: RequestInit) => getJson<EventsMeta>('/events/meta', init),
  eventTypes: (init?: RequestInit) => getJson<EventTypeCount[]>('/events/types', init),
  eventPoints: (params: Record<string, unknown>, init?: RequestInit) =>
    getJson<EventPoints>(`/events/geojson${toQuery(params)}`, init),
  event: (id: number, init?: RequestInit) => getJson<EventDetail>(`/events/${id}`, init),
  eventTimeseries: (params: Record<string, unknown>, init?: RequestInit) =>
    getJson<MonthCount[]>(`/events/timeseries${toQuery(params)}`, init),
  actors: (params: Record<string, unknown>, init?: RequestInit) =>
    getJson<ActorSummary[]>(`/actors${toQuery(params)}`, init),
  borderMetrics: (params: Record<string, unknown>, init?: RequestInit) =>
    getJson<MetricSeries>(`/border/metrics${toQuery(params)}`, init),
  seizures: (params: Record<string, unknown>, init?: RequestInit) =>
    getJson<SeizureSeries>(`/seizures${toQuery(params)}`, init),

  // Phase 2
  municipalities: (init?: RequestInit) =>
    getJson<ReferenceCollection<MunicipalityProps>>('/reference/municipalities', init),
  documents: (params: Record<string, unknown>, init?: RequestInit) =>
    getJson<DocumentPage>(`/documents${toQuery(params)}`, init),
  documentSources: (init?: RequestInit) => getJson<SourceCount[]>('/documents/sources', init),
  document: (id: number, init?: RequestInit) => getJson<DocumentDetail>(`/documents/${id}`, init),
  cluster: (id: number, init?: RequestInit) => getJson<ClusterDetail>(`/clusters/${id}`, init),
  designations: (params: Record<string, unknown>, init?: RequestInit) =>
    getJson<DesignationPage>(`/designations${toQuery(params)}`, init),
  crimeMeta: (init?: RequestInit) => getJson<CrimeMethodology[]>('/crime-incidence/meta', init),
  crime: (params: Record<string, unknown>, init?: RequestInit) =>
    getJson<CrimeChoropleth>(`/crime-incidence${toQuery(params)}`, init),
  llmUsage: (init?: RequestInit) => getJson<LLMUsage>('/llm/usage', init),
  labelQueue: (params: Record<string, unknown>, init?: RequestInit) =>
    getJson<LabelQueue>(`/labels/queue${toQuery(params)}`, init),
  putLabel: (body: LabelInput) => sendJson<LabelRecord>('PUT', '/labels', body),
  deleteLabel: (id: number) => sendJson<undefined>('DELETE', `/labels/${id}`),
}
