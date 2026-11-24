import { useState } from 'react'
import { Link } from 'react-router'
import { useGridLabelMutations, useGridReview } from '../api/hooks'
import type { GridLabelInput, GridReviewItem, Verdict } from '../api/types'
import { categoryLabel } from '../lib/priority'

type SourceFilter = 'all' | 'acled' | 'news'

const SOURCES: { value: SourceFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'acled', label: 'ACLED' },
  { value: 'news', label: 'News' },
]

const VERDICTS: { value: Verdict; label: string; tone: string; title: string }[] = [
  {
    value: 'correct',
    label: 'Correct',
    tone: 'border-emerald-500 bg-emerald-500/20 text-emerald-200',
    title: 'The kind and every indicator are right',
  },
  {
    value: 'partial',
    label: 'Partly wrong',
    tone: 'border-amber-500 bg-amber-500/20 text-amber-200',
    title: 'Name the kind or indicators that are wrong',
  },
  {
    value: 'incorrect',
    label: 'Wrong',
    tone: 'border-rose-500 bg-rose-500/20 text-rose-200',
    title: 'No grid interaction or indicator at all',
  },
]

function GridLabelControl({
  item,
  busy,
  onSave,
}: {
  item: GridReviewItem
  busy: boolean
  onSave: (body: GridLabelInput) => void
}) {
  const current = item.label
  const items = [...(item.kind ? ['kind'] : []), ...item.indicators]
  // A stale label may name items the event no longer has; keep only the current ones.
  const [wrong, setWrong] = useState<string[]>(
    current?.verdict === 'partial' ? current.wrong.filter((f) => items.includes(f)) : [],
  )
  const [open, setOpen] = useState(current?.verdict === 'partial' && !item.stale)
  const [note, setNote] = useState(current?.note ?? '')
  const save = (verdict: Verdict, names: string[] = []) =>
    onSave({ event_id: item.event_id, verdict, wrong: names, note: note || null })

  return (
    <div className="w-56 shrink-0 space-y-1.5">
      <div className="flex gap-1" role="group" aria-label="Grid verdict">
        {VERDICTS.map((v) => {
          const active =
            (current?.verdict === v.value && !item.stale) || (v.value === 'partial' && open)
          return (
            <button
              key={v.value}
              type="button"
              title={v.title}
              disabled={busy}
              aria-pressed={active}
              onClick={() => {
                if (v.value === 'partial') {
                  setOpen(true)
                } else {
                  setOpen(false)
                  save(v.value)
                }
              }}
              className={`flex-1 rounded border px-1 py-0.5 text-[11px] ${
                active ? v.tone : 'border-ink-700 text-ink-300 hover:bg-ink-800'
              }`}
            >
              {v.label}
            </button>
          )
        })}
      </div>
      {open && (
        <div className="border-ink-700 space-y-1 rounded border p-1.5">
          <p className="text-ink-400 text-[10px]">Wrong:</p>
          {items.map((f) => (
            <label key={f} className="flex items-center gap-1 text-[11px]">
              <input
                type="checkbox"
                className="accent-amber-500"
                checked={wrong.includes(f)}
                onChange={(e) =>
                  setWrong(e.target.checked ? [...wrong, f] : wrong.filter((x) => x !== f))
                }
              />
              {f === 'kind' ? `Kind (${categoryLabel(item.kind ?? '')})` : categoryLabel(f)}
            </label>
          ))}
          <button
            type="button"
            disabled={busy || wrong.length === 0}
            onClick={() => save('partial', wrong)}
            className="w-full rounded bg-amber-600 py-0.5 text-[11px] font-medium text-white disabled:opacity-40"
          >
            Save partial
          </button>
        </div>
      )}
      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        onBlur={() => {
          if (current && !item.stale && (note || null) !== current.note)
            save(current.verdict, current.wrong)
        }}
        placeholder="Note (optional)"
        aria-label="Note"
        className="border-ink-700 bg-ink-800 w-full rounded border px-1.5 py-0.5 text-[11px]"
      />
      {item.stale && (
        <p className="text-[10px] text-amber-300">
          Reclassified since it was labeled; label again.
        </p>
      )}
    </div>
  )
}

function ReviewRow({
  item,
  n,
  busy,
  onSave,
}: {
  item: GridReviewItem
  n: number
  busy: boolean
  onSave: (body: GridLabelInput) => void
}) {
  const where = [item.admin2_name, item.admin1_name].filter(Boolean).join(', ') || '—'
  const done = item.label && !item.stale
  return (
    <li className="border-ink-700 flex gap-4 border-t px-4 py-3 text-xs">
      <span className="text-ink-500 w-8 shrink-0 text-right tabular-nums">{n}</span>
      <span
        aria-label={done ? 'labeled' : 'to do'}
        className={`mt-1 h-2 w-2 shrink-0 rounded-full ${done ? 'bg-emerald-500' : item.stale ? 'bg-amber-500' : 'bg-ink-700'}`}
      />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-1.5">
          {item.source === 'acled' ? (
            <span className="rounded border border-sky-500/40 px-1 text-[10px] text-sky-300">
              ACLED {item.source_key}
            </span>
          ) : (
            item.document_ids.map((d) => (
              <Link
                key={d}
                to={`/news/${d}`}
                className="rounded border border-sky-500/40 px-1 text-[10px] text-sky-300 hover:bg-sky-500/10"
              >
                News document {d}
              </Link>
            ))
          )}
          <span className="text-ink-300">{item.event_date}</span>
          <span className="text-ink-400">· {where}</span>
          <span className="text-ink-500">
            · {item.event_type}
            {item.sub_event_type ? ` / ${item.sub_event_type}` : ''}
          </span>
        </div>
        <div className="flex flex-wrap gap-1">
          {item.kind && (
            <span className="rounded border border-violet-500/50 px-1 text-[10px] text-violet-300">
              Kind: {categoryLabel(item.kind)}
            </span>
          )}
          {item.indicators.map((i) => (
            <span
              key={i}
              className="rounded border border-dashed border-violet-400/40 px-1 text-[10px] text-violet-200"
            >
              Indicator: {categoryLabel(i)}
            </span>
          ))}
        </div>
        {item.actors.length > 0 && <p className="text-ink-400">Actors: {item.actors.join('; ')}</p>}
        <p className="text-ink-200">{item.description ?? '—'}</p>
        {item.evidence && (
          <p className="text-ink-400 border-ink-700 border-l-2 pl-2 italic">“{item.evidence}”</p>
        )}
        <p className="text-ink-600 text-[10px]">
          {item.prompt_version ?? 'prompt version unknown'}
        </p>
      </div>
      <GridLabelControl
        key={item.label?.updated_at ?? 'new'}
        item={item}
        busy={busy}
        onSave={onSave}
      />
    </li>
  )
}

/**
 * Grid-verdict labeling (ADR 0014 step 6): judge the grid-interaction kind and the energy
 * indicators on ACLED and news events. Measures precision only; the order interleaves kinds
 * and indicators so the rare ones come up early.
 */
export default function GridLabelingPage() {
  const [source, setSource] = useState<SourceFilter>('all')
  const [todoOnly, setTodoOnly] = useState(false)
  const review = useGridReview(source)
  const { save, remove } = useGridLabelMutations()
  const busy = save.isPending || remove.isPending
  const all = review.data?.items ?? []
  const shown = todoOnly ? all.filter((i) => !i.label || i.stale) : all
  const position = new Map(all.map((i, n) => [i.event_id, n + 1]))

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-3 px-6 py-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="space-y-1">
            <h1 className="text-ink-100 text-sm font-semibold">Grid labeling</h1>
            <p className="text-ink-400 text-xs">
              Judge the grid kind and indicators only. Wrong = no grid interaction or indicator at
              all. Labels are local and never sent to any API.{' '}
              <Link to="/labeling" className="text-sky-300 hover:underline">
                Record labeling →
              </Link>
            </p>
          </div>
          <div className="flex items-center gap-3 text-xs">
            <div className="flex gap-1" role="group" aria-label="Source">
              {SOURCES.map((s) => (
                <button
                  key={s.value}
                  type="button"
                  aria-pressed={source === s.value}
                  onClick={() => setSource(s.value)}
                  className={`rounded border px-2 py-0.5 ${
                    source === s.value
                      ? 'border-sky-500 bg-sky-500/20 text-sky-200'
                      : 'border-ink-700 text-ink-300 hover:bg-ink-800'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <label className="text-ink-300 flex items-center gap-1">
              <input
                type="checkbox"
                className="accent-sky-500"
                checked={todoOnly}
                onChange={(e) => setTodoOnly(e.target.checked)}
              />
              To do only
            </label>
          </div>
        </div>
        {review.data && (
          <div className="space-y-1">
            <div className="bg-ink-700 h-1.5 overflow-hidden rounded">
              <div
                className="h-full bg-sky-500"
                style={{
                  width: `${(review.data.labeled / Math.max(review.data.size, 1)) * 100}%`,
                }}
              />
            </div>
            <p className="text-ink-500 text-xs">
              {review.data.labeled} of {review.data.size} events labeled ·{' '}
              {Object.entries(review.data.strata)
                .map(([k, v]) => `${categoryLabel(k)} ${v}`)
                .join(' · ')}
            </p>
          </div>
        )}
        {save.isError && (
          <p className="text-xs text-rose-300">Could not save: {save.error.message}</p>
        )}
        {review.error && <p className="text-sm text-rose-300">{review.error.message}</p>}
        {review.isSuccess && shown.length === 0 && (
          <p className="text-ink-500 text-sm">
            {all.length === 0 ? 'No events with a grid kind or indicator yet.' : 'All labeled.'}
          </p>
        )}
        <ol aria-label="Grid review" className="border-ink-700 bg-ink-900 rounded border">
          {shown.map((item) => (
            <ReviewRow
              key={item.event_id}
              item={item}
              n={position.get(item.event_id) ?? 0}
              busy={busy}
              onSave={(body) => save.mutate(body)}
            />
          ))}
        </ol>
      </div>
    </div>
  )
}
