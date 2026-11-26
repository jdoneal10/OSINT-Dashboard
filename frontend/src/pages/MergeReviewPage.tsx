import { useState } from 'react'
import { Link } from 'react-router'
import { useMergeSuggestions, usePersonMutations } from '../api/hooks'
import type { MergeSuggestion } from '../api/types'
import Panel from '../components/news/Panel'
import { Chip } from './PersonsPage'

const BUTTON = 'rounded border px-2 py-1 disabled:cursor-not-allowed disabled:opacity-40'

/**
 * Possible duplicate people for the owner to confirm (ADR 0013 amendment 1). Nothing merges
 * without a click here, and every merge can be undone from the person's page.
 */
export default function MergeReviewPage() {
  const [includeUs, setIncludeUs] = useState(false)
  const { data, isPending, error } = useMergeSuggestions(includeUs)
  return (
    <div className="h-full overflow-y-auto px-6 py-4">
      <div className="mx-auto max-w-6xl space-y-4">
        <Link to="/persons" className="text-xs text-sky-400 hover:underline">
          ← People
        </Link>
        <header className="flex flex-wrap items-end gap-3">
          <div className="mr-auto">
            <h1 className="text-ink-100 text-lg font-semibold">Review possible duplicates</h1>
            <p className="text-ink-500 max-w-3xl text-xs">
              Suggestions only. Open the sources, tick the records that are the same person and
              choose whose name to show. Each record keeps its name as published, its citations and
              your labels. Any merge can be undone from the person&apos;s page. Outlets often
              reprint one another, so more records do not mean more confirmation.
            </p>
          </div>
          <label className="text-ink-300 flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              className="accent-amber-500"
              checked={includeUs}
              onChange={(e) => setIncludeUs(e.target.checked)}
            />
            Include U.S. persons
          </label>
        </header>
        {error && <p className="text-xs text-rose-300">Data unavailable: {error.message}</p>}
        {isPending && <p className="text-ink-500 text-xs">Loading…</p>}
        {data && data.hidden_us_persons > 0 && (
          <p className="text-xs text-amber-200">
            {data.hidden_us_persons} suggestion(s) involving a U.S. person are hidden.
          </p>
        )}
        {data?.items.length === 0 && (
          <p className="text-ink-500 text-xs">No possible duplicates to review.</p>
        )}
        {data?.items.map((s) => (
          // Keyed on membership, so a changed group never inherits old ticks.
          <Group key={s.candidates.map((c) => c.person.id).join('-')} suggestion={s} />
        ))}
      </div>
    </div>
  )
}

function Group({ suggestion }: { suggestion: MergeSuggestion }) {
  const { candidates, primary_id } = suggestion
  const { merge, distinct } = usePersonMutations()
  const [checked, setChecked] = useState(
    () => new Set(candidates.filter((c) => c.selected).map((c) => c.person.id)),
  )
  const [primary, setPrimary] = useState(primary_id)
  const name = candidates.find((c) => c.person.id === primary)?.person.display_name ?? ''
  const others = [...checked].filter((id) => id !== primary)
  const busy = merge.isPending || distinct.isPending

  const toggle = (id: number, on: boolean) => {
    const next = new Set(checked)
    if (on) next.add(id)
    else next.delete(id)
    setChecked(next)
  }

  return (
    <Panel title={name} aside={`${candidates.length} records`}>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-ink-500">
            <tr>
              <th className="py-1 pr-3 font-medium">Same</th>
              <th className="py-1 pr-3 font-medium">Show name</th>
              <th className="py-1 pr-3 font-medium">Name as published</th>
              <th className="py-1 pr-3 font-medium">Published by</th>
              <th className="py-1 pr-3 font-medium">Why suggested</th>
              <th className="py-1 font-medium">Not this person</th>
            </tr>
          </thead>
          <tbody className="divide-ink-800 divide-y">
            {candidates.map(({ person, sources, aliases, evidence, reasons, warning }) => (
              <tr key={person.id} className="align-top">
                <td className="py-1.5 pr-3">
                  <input
                    type="checkbox"
                    className="accent-sky-500"
                    aria-label={`Same person: record ${person.id}`}
                    checked={person.id === primary || checked.has(person.id)}
                    disabled={person.id === primary}
                    onChange={(e) => toggle(person.id, e.target.checked)}
                  />
                </td>
                <td className="py-1.5 pr-3">
                  <input
                    type="radio"
                    name={`primary-${primary_id}`}
                    className="accent-sky-500"
                    aria-label={`Show the name from record ${person.id}`}
                    checked={person.id === primary}
                    onChange={() => {
                      setPrimary(person.id)
                      toggle(person.id, true)
                    }}
                  />
                </td>
                <td className="max-w-sm py-1.5 pr-3">
                  <Link
                    to={`/persons/${person.id}${person.us_person ? '?us=1' : ''}`}
                    target="_blank"
                    className="text-sky-400 hover:underline"
                  >
                    {person.display_name}
                  </Link>
                  <span className="text-ink-500"> #{person.id}</span>
                  {person.us_person && <Chip tone="amber">U.S. person</Chip>}
                  {aliases.length > 0 && (
                    <p className="text-ink-300">Alias: {aliases.join(', ')}</p>
                  )}
                  {evidence && <p className="text-ink-500 italic">“{evidence}”</p>}
                </td>
                <td className="text-ink-300 py-1.5 pr-3">{sources.join(', ')}</td>
                <td className="text-ink-300 py-1.5 pr-3">
                  {reasons.join('; ')}
                  {warning && <p className="text-amber-300">{warning}</p>}
                </td>
                <td className="py-1.5">
                  {person.id !== primary && (
                    <button
                      className={`${BUTTON} border-ink-700 text-ink-300 hover:border-ink-500`}
                      aria-label={`Record ${person.id} is not the same person`}
                      disabled={busy}
                      onClick={() =>
                        distinct.mutate({ person_id: primary, other_ids: [person.id] })
                      }
                    >
                      Not the same
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <button
          className={`${BUTTON} border-sky-700 text-sky-200 hover:bg-sky-950`}
          disabled={busy || others.length === 0}
          onClick={() => merge.mutate({ person_ids: [primary, ...others], primary_id: primary })}
        >
          Merge {others.length + 1} records as “{name}”
        </button>
        {(merge.error ?? distinct.error) && (
          <span role="alert" className="text-rose-300">
            {(merge.error ?? distinct.error)?.message}
          </span>
        )}
      </div>
    </Panel>
  )
}
