import { useQuery } from '@tanstack/react-query'
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
