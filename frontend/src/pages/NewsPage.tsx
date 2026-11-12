import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useAoi, useDocumentFeed, useDocumentSources, useEventTypes } from '../api/hooks'
import type { DocumentSummary } from '../api/types'
import AcledAttribution from '../components/news/AcledAttribution'
import AdmiraltyBadge from '../components/news/AdmiraltyBadge'
import { useDebounced } from '../hooks/useDebounced'
import { feedParams } from '../lib/feed'
import { dateTime } from '../lib/format'

const STATUSES = [
  { value: 'extracted', label: 'Extracted (relevant)' },
  { value: 'filtered_out', label: 'Filtered out' },
  { value: 'quarantined', label: 'Quarantined' },
] as const

function corroboration(doc: DocumentSummary): number {
  return Math.max(0, ...doc.clusters.map((c) => c.n_independent_sources))
}

function FeedItem({ doc }: { doc: DocumentSummary }) {
  const sources = corroboration(doc)
  const conflicted = doc.clusters.some((c) => c.has_conflicts)
  return (
    <article className="border-ink-700 bg-ink-900 hover:border-ink-500 rounded-md border px-4 py-3 transition-colors">
      <header className="mb-1.5 flex flex-wrap items-center gap-2 text-xs">
        <AdmiraltyBadge grade={doc.admiralty} sources={sources} />
        <span className="text-ink-100 font-medium">{doc.source.name}</span>
        <span className="text-ink-500" title="Source reliability (Admiralty A–F)">
          {doc.source.reliability}
        </span>
        <span className="text-ink-500">·</span>
        <time className="text-ink-500" dateTime={doc.published_at ?? doc.retrieved_at}>
          {dateTime(doc.published_at ?? doc.retrieved_at)}
        </time>
        {doc.language && (
          <span className="border-ink-700 text-ink-500 rounded border px-1 uppercase">
            {doc.language}
          </span>
        )}
        {!doc.in_aoi && (
          <span className="rounded border border-amber-500/40 px-1 text-amber-300">
            outside AOI
          </span>
        )}
        {doc.clusters.some((c) => c.acled_corroborated) && (
          <span
            className="rounded border border-sky-500/40 px-1 text-sky-300"
            title="A matching ACLED event corroborates this report"
          >
            ACLED-corroborated
          </span>
        )}
        {conflicted && (
          <span className="rounded border border-rose-500/40 px-1 text-rose-300">
            conflicting reports
          </span>
        )}
      </header>
      <h2 className="text-sm leading-snug font-semibold">
        <Link to={`/news/${doc.id}`} className="text-ink-100 hover:text-sky-300">
          {doc.title ?? `Document ${doc.id}`}
        </Link>
      </h2>
      {doc.summary_en && (
        <p className="text-ink-300 mt-1 text-[13px] leading-relaxed">{doc.summary_en}</p>
      )}
      <footer className="text-ink-500 mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <span>
          {doc.n_events} event{doc.n_events === 1 ? '' : 's'} · {doc.n_seizures} seizure
          {doc.n_seizures === 1 ? '' : 's'}
        </span>
        {doc.clusters
          .filter((c) => c.n_documents > 1)
          .map((c) => (
            <Link key={c.id} to={`/clusters/${c.id}`} className="text-sky-400 hover:underline">
              Cluster {c.id}: {c.n_independent_sources} independent sources
            </Link>
          ))}
        {doc.url && (
          <a
            href={doc.url}
            target="_blank"
            rel="noreferrer noopener"
            className="hover:text-ink-300 ml-auto"
          >
            Original ↗
          </a>
        )}
      </footer>
    </article>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-ink-500 mb-1 block text-[10px] font-semibold tracking-[0.16em] uppercase">
        {label}
      </span>
      {children}
    </label>
  )
}

const INPUT =
  'border-ink-700 bg-ink-800 text-ink-100 w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none'

export default function NewsPage() {
  const [search, setSearch] = useSearchParams()
  const sources = useDocumentSources()
  const aoi = useAoi(2)
  const types = useEventTypes()

  const get = (k: string) => search.get(k) ?? ''
  const set = (k: string, v: string | string[] | boolean) =>
    setSearch(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.delete(k)
        if (Array.isArray(v)) v.forEach((x) => next.append(k, x))
        else if (v === true) next.set(k, 'true')
        else if (v) next.set(k, v)
        return next
      },
      { replace: true },
    )
  const selectedSources = search.getAll('source')
  const q = useDebounced(get('q'), 300)

  const key = search.toString()
  const params = useMemo(() => feedParams(new URLSearchParams(key), q), [key, q])
  const feed = useDocumentFeed(params)
  const docs = feed.data?.pages.flatMap((p) => p.items) ?? []
  const states = (aoi.data?.features ?? []).map((f) => f.properties)

  return (
    <div className="flex h-full">
      <aside
        aria-label="Feed filters"
        className="border-ink-700 bg-ink-900 w-72 shrink-0 space-y-4 overflow-y-auto border-r px-4 py-3"
      >
        <Field label="Search">
          <input
            type="search"
            value={get('q')}
            onChange={(e) => set('q', e.target.value)}
            placeholder="Title or English summary"
            className={INPUT}
          />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="From">
            <input
              type="date"
              value={get('start')}
              onChange={(e) => set('start', e.target.value)}
              className={INPUT}
            />
          </Field>
          <Field label="To">
            <input
              type="date"
              value={get('end')}
              onChange={(e) => set('end', e.target.value)}
              className={INPUT}
            />
          </Field>
        </div>
        <Field label="State">
          <select
            value={get('admin1')}
            onChange={(e) => set('admin1', e.target.value)}
            className={INPUT}
          >
            <option value="">All states</option>
            {states.map((s) => (
              <option key={s.slug} value={s.admin1_code ?? ''}>
                {s.name} ({s.country_iso3 === 'MEX' ? 'MX' : 'US'})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Event type">
          <select
            value={get('event_type')}
            onChange={(e) => set('event_type', e.target.value)}
            className={INPUT}
          >
            <option value="">All types</option>
            {(types.data ?? []).map((t) => (
              <option key={t.event_type} value={t.event_type}>
                {t.event_type}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Pipeline status">
          <select
            value={get('status')}
            onChange={(e) => set('status', e.target.value)}
            className={INPUT}
          >
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value === 'extracted' ? '' : s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </Field>
        <fieldset>
          <legend className="text-ink-500 mb-1 text-[10px] font-semibold tracking-[0.16em] uppercase">
            Sources
          </legend>
          {(sources.data ?? []).map((s) => (
            <label key={s.slug} className="flex items-center gap-2 py-0.5 text-xs">
              <input
                type="checkbox"
                className="accent-sky-500"
                checked={selectedSources.includes(s.slug)}
                onChange={(e) =>
                  set(
                    'source',
                    e.target.checked
                      ? [...selectedSources, s.slug]
                      : selectedSources.filter((x) => x !== s.slug),
                  )
                }
              />
              <span className="flex-1">{s.name}</span>
              <span className="text-ink-500 font-mono">{s.reliability}</span>
              <span className="text-ink-500 w-6 text-right tabular-nums">{s.documents}</span>
            </label>
          ))}
        </fieldset>
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            className="accent-sky-500"
            checked={get('out') === 'true'}
            onChange={(e) => set('out', e.target.checked)}
          />
          Include reports outside the AOI
        </label>
        <p className="text-ink-500 border-ink-700 border-t pt-3 text-[11px] leading-relaxed">
          Grades use the Admiralty scale: source reliability (A–F) and information credibility
          (1–6). Syndicated copies count once; single-source claims stay at 3 or lower.
        </p>
      </aside>
      <section aria-label="News feed" className="min-w-0 flex-1 overflow-y-auto px-6 py-4">
        <div className="mx-auto max-w-3xl space-y-3">
          <div className="text-ink-500 flex items-baseline justify-between text-xs">
            <h1 className="text-ink-100 text-sm font-semibold">News feed</h1>
            <span>
              {feed.isFetching && !feed.isFetchingNextPage ? 'Loading…' : `${docs.length} shown`}
            </span>
          </div>
          {feed.isError && (
            <p className="rounded bg-rose-950/80 px-3 py-2 text-xs text-rose-200">
              {feed.error.message}
            </p>
          )}
          {feed.isSuccess && docs.length === 0 && (
            <p className="text-ink-500 text-sm">
              No documents match. Run <code className="font-mono">make ingest SOURCE=news</code> and{' '}
              <code className="font-mono">make pipeline</code>, or widen the filters.
            </p>
          )}
          {docs.map((d) => (
            <FeedItem key={d.id} doc={d} />
          ))}
          {docs.some((d) => d.clusters.some((c) => c.acled_corroborated)) && (
            <AcledAttribution className="pt-1" />
          )}
          {feed.hasNextPage && (
            <button
              onClick={() => feed.fetchNextPage()}
              disabled={feed.isFetchingNextPage}
              className="border-ink-700 text-ink-300 hover:bg-ink-800 w-full rounded border py-2 text-xs"
            >
              {feed.isFetchingNextPage ? 'Loading…' : 'Load more'}
            </button>
          )}
        </div>
      </section>
    </div>
  )
}
