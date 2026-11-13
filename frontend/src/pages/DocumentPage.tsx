import { Link, useParams } from 'react-router'
import { useDocument } from '../api/hooks'
import DocumentHeader from '../components/news/DocumentHeader'
import Panel from '../components/news/Panel'
import { EventsTable, SeizuresTable } from '../components/news/RecordTables'
import { dateTime } from '../lib/format'

export default function DocumentPage() {
  const id = Number(useParams().id)
  const { data: doc, isPending, error } = useDocument(Number.isFinite(id) ? id : null)

  return (
    <div className="h-full overflow-y-auto px-6 py-4">
      <div className="mx-auto max-w-6xl space-y-4">
        <Link to="/news" className="text-ink-500 hover:text-ink-300 text-xs">
          ← News feed
        </Link>
        {isPending && <p className="text-ink-500 text-sm">Loading…</p>}
        {error && <p className="text-sm text-rose-300">{error.message}</p>}
        {doc && (
          <>
            <DocumentHeader doc={doc} />
            {doc.quarantine.length > 0 && (
              <div className="rounded border border-rose-500/40 bg-rose-950/40 px-3 py-2 text-xs text-rose-200">
                Model output for this document was quarantined (never written to core tables):{' '}
                {doc.quarantine
                  .map((q) => `${q.stage} · ${q.reason} · ${q.model}/${q.prompt_version}`)
                  .join('; ')}
              </div>
            )}
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel
                title={`Original${doc.language ? ` (${doc.language})` : ''}`}
                aside={
                  doc.text_policy === 'summary' ? 'feed summary only (source terms)' : 'full text'
                }
              >
                <div className="text-ink-300 max-h-[28rem] overflow-y-auto text-[13px] leading-relaxed whitespace-pre-line">
                  {doc.original_text ?? doc.feed_summary ?? 'No text stored.'}
                </div>
              </Panel>
              <Panel
                title="English summary"
                aside={doc.llm_model ? `${doc.llm_model} · ${doc.prompt_version}` : undefined}
              >
                {doc.summary_en ? (
                  <p className="text-ink-100 text-[13px] leading-relaxed">{doc.summary_en}</p>
                ) : (
                  <p className="text-ink-500 text-xs">Not yet processed by the extraction stage.</p>
                )}
                <p className="text-ink-500 mt-3 text-[11px] leading-relaxed">
                  Machine-generated from the public article text. Check figures against the original
                  before relying on them.
                </p>
              </Panel>
            </div>
            <Panel title="Extracted events" aside={`${doc.events.length}`}>
              <EventsTable events={doc.events} />
            </Panel>
            <Panel title="Extracted seizures" aside={`${doc.seizures.length}`}>
              <SeizuresTable seizures={doc.seizures} />
            </Panel>
            <Panel title="Provenance">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
                <dt className="text-ink-500">Retrieved</dt>
                <dd>{dateTime(doc.retrieved_at)}</dd>
                <dt className="text-ink-500">Relevance (local filter)</dt>
                <dd>
                  {doc.relevance_score !== null ? doc.relevance_score.toFixed(3) : '—'}
                  {doc.relevance_model && (
                    <span className="text-ink-500"> · {doc.relevance_model}</span>
                  )}
                </dd>
                <dt className="text-ink-500">Extraction</dt>
                <dd>
                  {doc.llm_model
                    ? `${doc.llm_model} · ${doc.prompt_version} · ${doc.llm_input_tokens ?? 0} in / ${doc.llm_output_tokens ?? 0} out tokens`
                    : '—'}
                </dd>
                {doc.duplicates.length > 0 && (
                  <>
                    <dt className="text-ink-500">Syndicated copies</dt>
                    <dd className="space-x-2">
                      {doc.duplicates.map((d) => (
                        <Link key={d} to={`/news/${d}`} className="text-sky-400 hover:underline">
                          #{d}
                        </Link>
                      ))}
                    </dd>
                  </>
                )}
                <dt className="text-ink-500">Labels</dt>
                <dd>
                  {doc.labels.length} ·{' '}
                  <Link to={`/labeling/${doc.id}`} className="text-sky-400 hover:underline">
                    Label this document
                  </Link>
                </dd>
              </dl>
            </Panel>
          </>
        )}
      </div>
    </div>
  )
}
