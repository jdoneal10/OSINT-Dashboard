import type { AreaProps, Health, NodeProps, ReferenceCollection } from './types'

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
    throw new ApiError(`GET ${path} failed with HTTP ${res.status}`, res.status)
  }
  return (await res.json()) as T
}

export const api = {
  health: (init?: RequestInit) => getJson<Health>('/health', init),
  aoi: (phase = 1, init?: RequestInit) =>
    getJson<ReferenceCollection<AreaProps>>(`/reference/aoi?phase=${phase}`, init),
  nodes: (init?: RequestInit) => getJson<ReferenceCollection<NodeProps>>('/reference/nodes', init),
}
