import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { api } from './client'
import type { LabelInput } from './types'

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

export const useAcledWeekly = (params: Record<string, unknown>, enabled = true) =>
  useQuery({
    queryKey: ['acled', 'weekly', params],
    queryFn: ({ signal }) => api.acledWeekly(params, { signal }),
    placeholderData: keepPreviousData,
    enabled,
  })

export const useAcledWeeklyMeta = (enabled = true) =>
  useQuery({
    queryKey: ['acled', 'weekly', 'meta'],
    queryFn: ({ signal }) => api.acledWeeklyMeta({ signal }),
    enabled,
  })

export const useAcledWeeklyStates = (params: Record<string, unknown>, enabled = true) =>
  useQuery({
    queryKey: ['acled', 'weekly', 'states', params],
    queryFn: ({ signal }) => api.acledWeeklyStates(params, { signal }),
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

// ---------------------------------------------------------------- Phase 2

export const useMunicipalities = (enabled = true) =>
  useQuery({
    queryKey: ['reference', 'municipalities'],
    queryFn: ({ signal }) => api.municipalities({ signal }),
    staleTime: Infinity,
    enabled,
  })

/** News feed with keyset pagination ("Load more"). */
export const useDocumentFeed = (params: Record<string, unknown>) =>
  useInfiniteQuery({
    queryKey: ['documents', 'feed', params],
    queryFn: ({ signal, pageParam }) =>
      api.documents({ ...params, cursor: pageParam ?? undefined }, { signal }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  })

export const useDocumentSources = () =>
  useQuery({
    queryKey: ['documents', 'sources'],
    queryFn: ({ signal }) => api.documentSources({ signal }),
  })

export const useDocument = (id: number | null) =>
  useQuery({
    queryKey: ['documents', 'detail', id],
    queryFn: ({ signal }) => api.document(id as number, { signal }),
    enabled: id !== null,
  })

export const useCluster = (id: number | null) =>
  useQuery({
    queryKey: ['clusters', id],
    queryFn: ({ signal }) => api.cluster(id as number, { signal }),
    enabled: id !== null,
  })

export const useDesignations = (params: Record<string, unknown>) =>
  useQuery({
    queryKey: ['designations', params],
    queryFn: ({ signal }) => api.designations(params, { signal }),
    placeholderData: keepPreviousData,
  })

export const useCrimeMeta = () =>
  useQuery({ queryKey: ['crime', 'meta'], queryFn: ({ signal }) => api.crimeMeta({ signal }) })

export const useCrime = (params: Record<string, unknown>, enabled = true) =>
  useQuery({
    queryKey: ['crime', params],
    queryFn: ({ signal }) => api.crime(params, { signal }),
    placeholderData: keepPreviousData,
    enabled,
  })

export const useLLMUsage = () =>
  useQuery({
    queryKey: ['llm', 'usage'],
    queryFn: ({ signal }) => api.llmUsage({ signal }),
    refetchInterval: 60_000,
    retry: false,
  })

export const useLabelQueue = (size = 100, recordDocuments = 0) =>
  useQuery({
    queryKey: ['labels', 'queue', size, recordDocuments],
    queryFn: ({ signal }) =>
      api.labelQueue({ size, record_documents: recordDocuments || undefined }, { signal }),
  })

/** Save (create or replace) or delete a label; refreshes the document and the queue. */
export function useLabelMutations(documentId: number) {
  const qc = useQueryClient()
  const refresh = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['documents', 'detail', documentId] }),
      qc.invalidateQueries({ queryKey: ['labels', 'queue'] }),
    ])
  const save = useMutation({
    mutationFn: (body: LabelInput) => api.putLabel(body),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteLabel(id),
    onSuccess: refresh,
  })
  return { save, remove }
}

/** Priority panels (ADR 0009). */
export const usePriorityUxs = (params: Record<string, unknown>) =>
  useQuery({
    queryKey: ['priority', 'uxs', params],
    queryFn: ({ signal }) => api.priorityUxs(params, { signal }),
    placeholderData: keepPreviousData,
  })

export const usePriorityEnergy = (params: Record<string, unknown>) =>
  useQuery({
    queryKey: ['priority', 'energy', params],
    queryFn: ({ signal }) => api.priorityEnergy(params, { signal }),
    placeholderData: keepPreviousData,
  })

export const useEventList = (params: Record<string, unknown>, enabled = true) =>
  useQuery({
    queryKey: ['events', 'list', params],
    queryFn: ({ signal }) => api.events(params, { signal }),
    placeholderData: keepPreviousData,
    enabled,
  })

/** Person records (ADR 0013). U.S. persons stay hidden unless includeUs is set. */
export const usePersons = (params: Record<string, unknown>) =>
  useQuery({
    queryKey: ['persons', 'list', params],
    queryFn: ({ signal }) => api.persons(params, { signal }),
    placeholderData: keepPreviousData,
  })

export const usePerson = (id: number | null, includeUs = false) =>
  useQuery({
    queryKey: ['persons', 'detail', id, includeUs],
    queryFn: ({ signal }) =>
      api.person(id as number, { include_us_persons: includeUs || undefined }, { signal }),
    enabled: id !== null,
    retry: false,
  })

export const useMergeSuggestions = (includeUs: boolean) =>
  useQuery({
    queryKey: ['persons', 'suggestions', includeUs],
    queryFn: ({ signal }) =>
      api.mergeSuggestions({ include_us_persons: includeUs || undefined }, { signal }),
  })

export function usePersonMutations() {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: ['persons'] })
  return {
    dispute: useMutation({
      mutationFn: (v: { id: number; disputed: boolean; note?: string | null }) =>
        api.disputePerson(v.id, { disputed: v.disputed, note: v.note }),
      onSuccess: refresh,
    }),
    merge: useMutation({
      mutationFn: (v: { person_ids: number[]; primary_id: number }) => api.mergePersons(v),
      onSuccess: refresh,
    }),
    undo: useMutation({ mutationFn: (id: number) => api.undoMerge(id), onSuccess: refresh }),
    distinct: useMutation({
      mutationFn: (v: { person_id: number; other_ids: number[] }) => api.markDistinct(v),
      onSuccess: refresh,
    }),
    clearDistinct: useMutation({
      mutationFn: (id: number) => api.clearDistinct(id),
      onSuccess: refresh,
    }),
    remove: useMutation({ mutationFn: (id: number) => api.deletePerson(id), onSuccess: refresh }),
  }
}
