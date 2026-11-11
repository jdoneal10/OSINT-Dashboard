import { describe, expect, it, vi } from 'vitest'
import { ApiError, api } from './client'

describe('api client', () => {
  it('returns parsed JSON on success', async () => {
    const body = {
      status: 'ok',
      version: '0.1.0',
      db: 'ok',
      postgis_version: '3.5.3',
      worker_last_heartbeat: null,
    }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(api.health()).resolves.toEqual(body)
    expect(fetchMock).toHaveBeenCalledWith('/api/health', expect.anything())
  })

  it('raises ApiError with status on HTTP failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 503 })))
    const err = await api.health().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(503)
  })

  it('raises ApiError with null status when unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const err = await api.health().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBeNull()
  })
})
