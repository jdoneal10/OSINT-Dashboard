/** API params for the feed from the URL search params (the filters live in the URL). */
export function feedParams(search: URLSearchParams, q: string): Record<string, unknown> {
  const get = (k: string) => search.get(k) || undefined
  const sources = search.getAll('source')
  return {
    start: get('start'),
    end: get('end'),
    source: sources.length ? sources : undefined,
    admin1: get('admin1'),
    event_type: get('event_type'),
    status: get('status'),
    include_out_of_aoi: search.get('out') === 'true' || undefined,
    q: q || undefined,
    limit: 25,
  }
}
