import { Link, useParams } from 'react-router'
import { useCluster } from '../api/hooks'
import AdmiraltyBadge from '../components/news/AdmiraltyBadge'
import Panel from '../components/news/Panel'
import { EventsTable } from '../components/news/RecordTables'
import { describeGrade } from '../lib/admiralty'
import { dateTime, plural } from '../lib/format'

function value(v: unknown): string {
  return v === null || v === undefined ? '—' : Array.isArray(v) ? v.join(', ') : String(v)
}

export default function ClusterPage() {
  const id = Number(useParams().id)
  const { data: c, isPending, error } = useCluster(Number.isFinite(id) ? id : null)
  return (
    <div className="h-full overflow-y-auto px-6 py-4">
      <div className="mx-auto max-w-6xl space-y-4">
        <Link to="/news" className="text-ink-500 hover:text-ink-300 text-xs">
          ← News feed
        </Link>
        {isPending && <p className="text-ink-500 text-sm">Loading…</p>}
        {error && <p className="text-sm text-rose-300">{error.message}</p>}
        {c && (
          <>
            <header className="space-y-1">
              <div className="flex items-center gap-3">
                <AdmiraltyBadge grade={c.admiralty} size="md" />
                <h1 className="text-ink-100 text-lg font-semibold">
                  Cluster {c.id}: {c.event_type}
                </h1>
              </div>
              <p className="text-ink-500 text-xs">
                {c.first_date === c.last_date ? c.first_date : `${c.first_date} to ${c.last_date}`}
                {c.admin1_code && ` · ${c.admin1_code}`} · {plural(c.n_events, 'event')} from{' '}
                {plural(c.n_documents, 'document')},{' '}
                {plural(c.n_independent_sources, 'independent source')} ·{' '}
                {describeGrade(c.admiralty)}
              </p>
            </header>

            {Object.keys(c.conflicts).length > 0 && (
              <Panel title="Conflicting reports">
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
                  {Object.entries(c.conflicts).map(([field, values]) => (
                    <div key={field} className="contents">
                      <dt className="text-ink-500">{field}</dt>
                      <dd>{value(values)}</dd>
                    </div>
                  ))}
                </dl>
              </Panel>
            )}

            <Panel
              title="Analytic assessment"
              aside={
                c.assessments[0]
                  ? `${c.assessments[0].llm_model} · ${c.assessments[0].prompt_version}`
                  : undefined
              }
            >
              {c.assessments.length === 0 ? (
                <p className="text-ink-500 text-xs">
                  None. Sonnet assesses clusters with conflicting reports or high significance.
                </p>
              ) : (
                c.assessments.slice(0, 1).map((a) => (
                  <div key={a.id} className="space-y-2 text-[13px]">
                    <p className="text-ink-100 leading-relaxed">{a.judgment}</p>
                    <p className="text-ink-500 text-xs">
                      Likelihood: <b className="text-ink-300">{a.likelihood ?? '—'}</b> · Analytic
                      confidence: <b className="text-ink-300">{a.analytic_confidence ?? '—'}</b> ·{' '}
                      {dateTime(a.created_at)}
                    </p>
                    {Object.keys(a.resolved).length > 0 && (
                      <p className="text-ink-500 text-xs">
                        Best-supported values:{' '}
                        {Object.entries(a.resolved)
                          .map(([k, v]) => `${k} ${value(v)}`)
                          .join(' · ')}
                      </p>
                    )}
                    <p className="text-ink-500 text-xs">
                      Cites:{' '}
                      {a.cited_document_ids.map((d) => (
                        <Link
                          key={d}
                          to={`/news/${d}`}
                          className="mr-2 text-sky-400 hover:underline"
                        >
                          document {d}
                        </Link>
                      ))}
                    </p>
                  </div>
                ))
              )}
            </Panel>

            <Panel title="Member events" aside={`${c.events.length}`}>
              <EventsTable events={c.events} />
            </Panel>

            <Panel title="Reporting" aside={`${c.documents.length}`}>
              <ul className="divide-ink-700 divide-y text-xs">
                {c.documents.map((d) => (
                  <li key={d.id} className="flex items-baseline gap-3 py-2">
                    <span className="text-ink-500 w-28 shrink-0">{d.source.name}</span>
                    <Link to={`/news/${d.id}`} className="text-ink-100 hover:text-sky-300">
                      {d.title ?? `Document ${d.id}`}
                    </Link>
                    <span className="text-ink-500 ml-auto shrink-0">
                      {dateTime(d.published_at ?? d.retrieved_at)}
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>
          </>
        )}
      </div>
    </div>
  )
}
