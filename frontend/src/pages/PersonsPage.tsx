import { useState } from 'react'
import { Link } from 'react-router'
import { usePersons } from '../api/hooks'
import Panel from '../components/news/Panel'
import { categoryLabel } from '../lib/priority'
import { PERSON_ROLE_LABELS } from '../lib/persons'

const INPUT =
  'border-ink-700 bg-ink-800 text-ink-100 rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none'
const PAGE = 50

/**
 * People an open source links to criminal activity (hard rule 3; ADR 0008, ADR 0013).
 * U.S. persons are hidden by default; every attribute on the detail page is cited.
 */
export default function PersonsPage() {
  const [q, setQ] = useState('')
  const [includeUs, setIncludeUs] = useState(false)
  const [hideDisputed, setHideDisputed] = useState(false)
  const [offset, setOffset] = useState(0)
  const { data, isPending, error } = usePersons({
    q: q.trim() || undefined,
    include_us_persons: includeUs || undefined,
    include_disputed: hideDisputed ? false : undefined,
    limit: PAGE,
    offset,
  })
  const reset =
    <T,>(fn: (v: T) => void) =>
    (v: T) => {
      fn(v)
      setOffset(0)
    }

  return (
    <div className="h-full overflow-y-auto px-6 py-4">
      <div className="mx-auto max-w-6xl space-y-4">
        <header className="flex flex-wrap items-end gap-3">
          <div className="mr-auto">
            <h1 className="text-ink-100 text-lg font-semibold">People</h1>
            <p className="text-ink-500 max-w-3xl text-xs">
              Individuals an open source links to criminal activity, as reported. Every attribute
              and link cites its source, date and Admiralty grade. Victims, bystanders, witnesses,
              journalists and minors are never recorded.
            </p>
          </div>
          <input
            type="search"
            aria-label="Search names and aliases"
            placeholder="Name or alias"
            value={q}
            onChange={(e) => reset(setQ)(e.target.value)}
            className={`${INPUT} w-56`}
          />
          <label className="text-ink-300 flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              className="accent-sky-500"
              checked={hideDisputed}
              onChange={(e) => reset(setHideDisputed)(e.target.checked)}
            />
            Hide disputed
          </label>
          <label className="text-ink-300 flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              className="accent-amber-500"
              checked={includeUs}
              onChange={(e) => reset(setIncludeUs)(e.target.checked)}
            />
            Include U.S. persons
          </label>
        </header>
        {includeUs && (
          <p className="rounded border border-amber-700/60 bg-amber-950/40 px-3 py-2 text-xs text-amber-200">
            Showing records reported as U.S. citizens, residents or U.S.-located. They are hidden by
            default (the owner&apos;s EO 12333 boundary); the flag is a safeguard, not a
            determination.
          </p>
        )}

        <Panel title="Records" aside={data ? `${data.total.toLocaleString()} matching` : undefined}>
          {error && <p className="text-xs text-rose-300">Data unavailable: {error.message}</p>}
          {isPending && <p className="text-ink-500 text-xs">Loading…</p>}
          {data && data.items.length === 0 && (
            <p className="text-ink-500 text-xs">
              No person records{q ? ' match this search' : ' yet'}. They appear as documents are
              extracted with prompt extract-v9 or later.
            </p>
          )}
          {data && data.items.length > 0 && (
            <table className="w-full text-left text-xs">
              <thead className="text-ink-500">
                <tr>
                  <th className="py-1 pr-3 font-medium">Name (as reported)</th>
                  <th className="py-1 pr-3 font-medium">Reported role</th>
                  <th className="py-1 pr-3 font-medium">Organizations</th>
                  <th className="py-1 pr-3 font-medium">Sources</th>
                  <th className="py-1 font-medium">Last reported</th>
                </tr>
              </thead>
              <tbody className="divide-ink-800 divide-y">
                {data.items.map((p) => (
                  <tr key={p.id}>
                    <td className="py-1.5 pr-3">
                      <Link
                        to={`/persons/${p.id}${p.us_person ? '?us=1' : ''}`}
                        className="text-sky-400 hover:underline"
                      >
                        {p.display_name}
                      </Link>
                      {p.disputed && <Chip tone="rose">disputed</Chip>}
                      {p.us_person && <Chip tone="amber">U.S. person</Chip>}
                    </td>
                    <td className="text-ink-300 py-1.5 pr-3">
                      {p.roles.map((r) => PERSON_ROLE_LABELS[r] ?? categoryLabel(r)).join(', ') ||
                        '—'}
                    </td>
                    <td className="text-ink-300 py-1.5 pr-3">
                      {p.organizations.join(', ') || '—'}
                    </td>
                    <td className="text-ink-300 py-1.5 pr-3 tabular-nums">{p.n_sources}</td>
                    <td className="text-ink-300 py-1.5 tabular-nums">
                      {p.last_reported_on ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {data && data.total > PAGE && (
            <div className="text-ink-500 mt-3 flex items-center justify-end gap-2 text-xs">
              <button
                className="hover:text-ink-100 disabled:opacity-40"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE))}
              >
                ← Previous
              </button>
              <span>
                {offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}
              </span>
              <button
                className="hover:text-ink-100 disabled:opacity-40"
                disabled={offset + PAGE >= data.total}
                onClick={() => setOffset(offset + PAGE)}
              >
                Next →
              </button>
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}

export function Chip({ tone, children }: { tone: 'rose' | 'amber'; children: string }) {
  const cls =
    tone === 'rose' ? 'border-rose-700/60 text-rose-300' : 'border-amber-700/60 text-amber-300'
  return <span className={`ml-2 rounded border px-1 text-[10px] uppercase ${cls}`}>{children}</span>
}
