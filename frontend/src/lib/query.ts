/** Build a query string; arrays repeat the key (FastAPI list params), empty values are dropped. */
export function toQuery(params: Record<string, unknown>): string {
  const q = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) value.forEach((v) => q.append(key, String(v)))
    else q.append(key, String(value))
  }
  const s = q.toString()
  return s ? `?${s}` : ''
}
