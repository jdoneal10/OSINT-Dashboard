import { Link, useNavigate, useParams } from 'react-router'
import { useDocument, useLabelMutations, useLabelQueue } from '../api/hooks'
import type { DocumentDetail, LabelRecord, LabelTarget, Verdict } from '../api/types'
import DocumentHeader from '../components/news/DocumentHeader'
import LabelControl from '../components/news/LabelControl'
import type { LabelChange } from '../lib/labels'
import Panel from '../components/news/Panel'
import { EventsTable, SeizuresTable } from '../components/news/RecordTables'

const SAMPLE_SIZE = 100

function recordLabel(doc: DocumentDetail, table: LabelTarget, id: number): LabelRecord | undefined {
  return doc.labels.find(
    (l) =>
      l.target_table === table &&
      l.target_id === id &&
      (table !== 'documents' || l.field === 'relevant'),
  )
}

function Workbench({ doc }: { doc: DocumentDetail }) {
  const { save, remove } = useLabelMutations(doc.id)
  const busy = save.isPending || remove.isPending

  /** One label per record: replace any earlier label stored under a different field. */
  const saveRecord = async (table: 'events' | 'seizures', id: number, change: LabelChange) => {
    const stale = doc.labels.filter(
      (l) => l.target_table === table && l.target_id === id && l.field !== change.field,
    )
    for (const l of stale) await remove.mutateAsync(l.id)
    save.mutate({ document_id: doc.id, target_table: table, target_id: id, ...change })
  }
  const relevance = recordLabel(doc, 'documents', doc.id)
  const setRelevance = (verdict: Verdict) =>
    save.mutate({
      document_id: doc.id,
      target_table: 'documents',
      target_id: doc.id,
      field: 'relevant',
      verdict,
    })
  const judged = doc.status === 'extracted' ? 'relevant' : 'not relevant'

  return (
    <div className="space-y-4">
      <DocumentHeader doc={doc} />
      {save.isError && (
        <p className="text-xs text-rose-300">Could not save: {save.error.message}</p>
      )}
      <Panel title="1 · Relevance decision" aside={`pipeline judged: ${judged}`}>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span className="text-ink-300">
            Is this article about organized crime in the AOI (so it <i>should</i> be {judged})?
          </span>
          {(['correct', 'incorrect'] as const).map((v) => (
            <button
              key={v}
              type="button"
              disabled={busy}
              aria-pressed={relevance?.verdict === v}
              onClick={() => setRelevance(v)}
              className={`rounded border px-2 py-0.5 ${
                relevance?.verdict === v
                  ? v === 'correct'
                    ? 'border-emerald-500 bg-emerald-500/20 text-emerald-200'
                    : 'border-rose-500 bg-rose-500/20 text-rose-200'
                  : 'border-ink-700 text-ink-300 hover:bg-ink-800'
              }`}
            >
              {v === 'correct' ? 'Decision correct' : 'Decision wrong'}
            </button>
          ))}
        </div>
      </Panel>
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title={`Source text${doc.language ? ` (${doc.language})` : ''}`}>
          <div className="text-ink-300 max-h-80 overflow-y-auto text-[13px] leading-relaxed whitespace-pre-line">
            {doc.original_text ?? doc.feed_summary ?? 'No text stored.'}
          </div>
        </Panel>
        <Panel title="English summary">
          <p className="text-ink-100 text-[13px] leading-relaxed">{doc.summary_en ?? '—'}</p>
        </Panel>
      </div>
      <Panel title="2 · Extracted events" aside={`${doc.events.length}`}>
        <EventsTable
          events={doc.events}
          actions={(ev) => (
            <LabelControl
              key={`e${ev.id}-${recordLabel(doc, 'events', ev.id)?.updated_at ?? ''}`}
              table="events"
              outsideAoi={!ev.in_aoi}
              current={recordLabel(doc, 'events', ev.id)}
              busy={busy}
              onSave={(c) => void saveRecord('events', ev.id, c)}
            />
          )}
        />
      </Panel>
      <Panel title="3 · Extracted seizures" aside={`${doc.seizures.length}`}>
        <SeizuresTable
          seizures={doc.seizures}
          actions={(s) => (
            <LabelControl
              key={`s${s.id}-${recordLabel(doc, 'seizures', s.id)?.updated_at ?? ''}`}
              table="seizures"
              outsideAoi={!s.in_aoi}
              current={recordLabel(doc, 'seizures', s.id)}
              busy={busy}
              onSave={(c) => void saveRecord('seizures', s.id, c)}
            />
          )}
        />
      </Panel>
      <p className="text-ink-500 text-[11px]">
        A record missing from the extraction cannot be labeled here; note it under the relevance
        decision or in the evaluation report. Labels are local and never sent to any API.
      </p>
    </div>
  )
}

export default function LabelingPage() {
  const params = useParams()
  const navigate = useNavigate()
  const queue = useLabelQueue(SAMPLE_SIZE)
  const items = queue.data?.items ?? []
  const fromUrl = params.id ? Number(params.id) : null
  const currentId = fromUrl ?? items.find((i) => !i.done)?.document_id ?? null
  const doc = useDocument(currentId)
  const index = items.findIndex((i) => i.document_id === currentId)
  const next =
    items.slice(index + 1).find((i) => !i.done) ??
    items.find((i) => !i.done && i.document_id !== currentId)

  return (
    <div className="flex h-full">
      <aside
        aria-label="Labeling queue"
        className="border-ink-700 bg-ink-900 flex w-72 shrink-0 flex-col border-r"
      >
        <div className="border-ink-700 space-y-1.5 border-b px-4 py-3">
          <h1 className="text-ink-100 text-sm font-semibold">Precision labeling</h1>
          {queue.data && (
            <>
              <div className="bg-ink-700 h-1.5 overflow-hidden rounded">
                <div
                  className="h-full bg-sky-500"
                  style={{ width: `${(queue.data.done / Math.max(SAMPLE_SIZE, 1)) * 100}%` }}
                />
              </div>
              <p className="text-ink-500 text-xs">
                {queue.data.done} of {queue.data.size} documents done
                {queue.data.size < SAMPLE_SIZE &&
                  ` (sample target ${SAMPLE_SIZE}; more as feeds run)`}
              </p>
            </>
          )}
        </div>
        <ol className="flex-1 overflow-y-auto py-1 text-xs">
          {items.map((i, n) => (
            <li key={i.document_id}>
              <Link
                to={`/labeling/${i.document_id}`}
                className={`flex items-start gap-2 px-4 py-1.5 ${
                  i.document_id === currentId ? 'bg-ink-800' : 'hover:bg-ink-800/60'
                }`}
              >
                <span className="text-ink-500 w-6 shrink-0 text-right tabular-nums">{n + 1}</span>
                <span
                  aria-label={i.done ? 'done' : 'to do'}
                  className={`mt-1 h-2 w-2 shrink-0 rounded-full ${i.done ? 'bg-emerald-500' : i.n_labeled_records || i.relevance_labeled ? 'bg-amber-500' : 'bg-ink-700'}`}
                />
                <span className="min-w-0 flex-1">
                  <span className="text-ink-100 line-clamp-2">
                    {i.title ?? `Document ${i.document_id}`}
                  </span>
                  <span className="text-ink-500">
                    {i.source} ·{' '}
                    {i.status === 'extracted'
                      ? `${i.n_labeled_records}/${i.n_records} records`
                      : 'filtered out'}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
      </aside>
      <section aria-label="Labeling workbench" className="min-w-0 flex-1 overflow-y-auto px-6 py-4">
        <div className="mx-auto max-w-6xl space-y-3">
          <div className="flex justify-end">
            {next && (
              <button
                type="button"
                onClick={() => navigate(`/labeling/${next.document_id}`)}
                className="rounded bg-sky-600 px-3 py-1 text-xs font-medium text-white hover:bg-sky-500"
              >
                Next unlabeled →
              </button>
            )}
          </div>
          {queue.isSuccess && items.length === 0 && (
            <p className="text-ink-500 text-sm">No processed documents to label yet.</p>
          )}
          {doc.error && <p className="text-sm text-rose-300">{doc.error.message}</p>}
          {doc.data && <Workbench key={doc.data.id} doc={doc.data} />}
        </div>
      </section>
    </div>
  )
}
