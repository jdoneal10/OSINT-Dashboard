import { vi } from 'vitest'

/** Route fetch calls by URL path prefix to canned JSON bodies; unknown paths return 404. */
export function mockApi(routes: Record<string, unknown>) {
  // ``init`` is part of the signature so tests can read method and body from mock.calls.
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    void init
    const url = new URL(String(input), 'http://localhost')
    const path = url.pathname.replace(/^\/api/, '')
    const key = Object.keys(routes)
      .sort((a, b) => b.length - a.length)
      .find((k) => path === k || path.startsWith(`${k}/`) || path.startsWith(`${k}?`))
    if (key === undefined) return new Response('{}', { status: 404 })
    return new Response(JSON.stringify(routes[key]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fn)
  return fn
}
