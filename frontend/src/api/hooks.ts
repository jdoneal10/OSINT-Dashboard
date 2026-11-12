import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from './client'

export const useHealth = () =>
  useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => api.health({ signal }),
    refetchInterval: 30_000,
    retry: false,
  })

export const useAoi = (phase = 1) =>
  useQuery({
    queryKey: ['reference', 'aoi', phase],
    queryFn: ({ signal }) => api.aoi(phase, { signal }),
    staleTime: Infinity,
  })

export const useNodes = () =>
  useQuery({
    queryKey: ['reference', 'nodes'],
    queryFn: ({ signal }) => api.nodes({ signal }),
    staleTime: Infinity,
  })

export const useAdjacency = () =>
  useQuery({
    queryKey: ['reference', 'adjacency'],
    queryFn: ({ signal }) => api.adjacency({ signal }),
    staleTime: Infinity,
  })

export const useEventsMeta = () =>
  useQuery({ queryKey: ['events', 'meta'], queryFn: ({ signal }) => api.eventsMeta({ signal }) })

export const useEventTypes = () =>
  useQuery({ queryKey: ['events', 'types'], queryFn: ({ signal }) => api.eventTypes({ signal }) })

export const useEventPoints = (params: Record<string, unknown>, enabled = true) =>
  useQuery({
    queryKey: ['events', 'points', params],
    queryFn: ({ signal }) => api.eventPoints(params, { signal }),
    placeholderData: keepPreviousData,
    enabled,
  })

export const useEvent = (id: number | null) =>
  useQuery({
    queryKey: ['events', 'detail', id],
    queryFn: ({ signal }) => api.event(id as number, { signal }),
    enabled: id !== null,
  })

export const useEventTimeseries = (params: Record<string, unknown>, enabled = true) =>
  useQuery({
    queryKey: ['events', 'timeseries', params],
    queryFn: ({ signal }) => api.eventTimeseries(params, { signal }),
    placeholderData: keepPreviousData,
    enabled,
  })

export const useActorSearch = (q: string) =>
  useQuery({
    queryKey: ['actors', q],
    queryFn: ({ signal }) => api.actors({ q, with_events: true, limit: 20 }, { signal }),
    enabled: q.trim().length >= 2,
  })

export const useBorderMetrics = (params: Record<string, unknown>, enabled = true) =>
  useQuery({
    queryKey: ['border', 'metrics', params],
    queryFn: ({ signal }) => api.borderMetrics(params, { signal }),
    placeholderData: keepPreviousData,
    enabled,
  })

export const useSeizures = (params: Record<string, unknown>, enabled = true) =>
  useQuery({
    queryKey: ['border', 'seizures', params],
    queryFn: ({ signal }) => api.seizures(params, { signal }),
    placeholderData: keepPreviousData,
    enabled,
  })
