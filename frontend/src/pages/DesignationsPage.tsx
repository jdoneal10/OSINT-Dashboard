import { useState } from 'react'
import { useDesignations } from '../api/hooks'
import Panel from '../components/news/Panel'

const TYPES = [
  { value: '', label: 'All types' },
  { value: 'fto', label: 'FTO (State, INA 219)' },
  { value: 'sdgt', label: 'SDGT (EO 13224)' },
  { value: 'sdn', label: 'OFAC SDN listing' },
]
const PROGRAMS = ['', 'SDNTK', 'ILLICIT-DRUGS-EO14059', 'TCO', 'SDGT', 'FTO']
const PAGE = 50

const INPUT =
  'border-ink-700 bg-ink-800 text-ink-100 rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none'

export default function DesignationsPage() {
  const [type, setType] = useState('')
  const [program, setProgram] = useState('')
  const [individuals, setIndividuals] = useState(false)
  const [offset, setOffset] = useState(0)
  const { data, isPending, error, isFetching } = useDesignations({
    type: type || undefined,
    program: program || undefined,
    include_individual_listings: individuals || undefined,
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
            <h1 className="text-ink-100 text-lg font-semibold">Designations and sanctions</h1>
            <p className="text-ink-500 text-xs">
              Public U.S. legal actions with a Mexico or Central America nexus: FTO and SDGT
              designations (Federal Register) and OFAC SDN listings.
            </p>
          </div>
          <select
            aria-label="Type"
            value={type}
            onChange={(e) => reset(setType)(e.target.value)}
            className={INPUT}
          >
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
          <select
            aria-label="Program"
            value={program}
            onChange={(e) => reset(setProgram)(e.target.value)}
            className={INPUT}
          >
            {PROGRAMS.map((p) => (
              <option key={p} value={p}>
                {p || 'All programs'}
              </option>
            ))}
          </select>
          <label className="text-ink-300 flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              className="accent-sky-500"
              checked={individuals}
              onChange={(e) => reset(setIndividuals)(e.target.checked)}
            />
            Include individual listings
          </label>
        </header>
        {individuals && (
          <p className="rounded border border-amber-500/40 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
            Individuals appear only as named in the public OFAC record, as an attribute of that
            listing. This dashboard does not profile or track people.
          </p>
        )}
        {error && <p className="text-sm text-rose-300">{error.message}</p>}
        <Panel
          title="Actions"
          aside={
            data
              ? `${data.total.toLocaleString()} records${isFetching ? ' · loading…' : ''}`
              : undefined
          }
        >
          {isPending ? (
            <p className="text-ink-500 text-xs">Loading…</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-ink-500 text-left text-[10px] tracking-wider uppercase">
                  <th className="py-1.5 pr-3">Date</th>
                  <th className="pr-3">Type</th>
                  <th className="pr-3">Program</th>
                  <th className="pr-3">Listed party</th>
                  <th className="pr-3">Linked organizations</th>
                  <th>Record</th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((d) => (
                  <tr key={d.id} className="border-ink-700 border-t align-top">
                    <td className="py-2 pr-3 whitespace-nowrap tabular-nums">
                      {d.designation_type === 'sdn' ? (
                        <span title="The SDN file carries no listing date: first seen in our pulls of the list">
                          ≤ {d.action_date}
                        </span>
                      ) : (
                        d.action_date
                      )}
                    </td>
                    <td className="pr-3 uppercase">{d.designation_type}</td>
                    <td className="text-ink-300 pr-3">{d.program?.replaceAll(';', ', ') ?? '—'}</td>
                    <td className="pr-3">
                      {d.listed_parties.map((p) => (
                        <div key={p.name}>
                          {p.name}
                          <span className="text-ink-500"> · {p.type}</span>
                        </div>
                      ))}
                      {d.designation_type !== 'sdn' && (
                        <div className="text-ink-500 mt-0.5">{d.title}</div>
                      )}
                    </td>
                    <td className="text-ink-300 pr-3">
                      {d.actors.map((a) => a.name).join(', ') || '—'}
                    </td>
                    <td>
                      {d.source_url ? (
                        <a
                          href={d.source_url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="text-sky-400 hover:underline"
                        >
                          {d.source.toUpperCase()} ↗
                        </a>
                      ) : (
                        d.source.toUpperCase()
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {data && data.total > PAGE && (
            <div className="text-ink-500 mt-3 flex items-center justify-between text-xs">
              <button
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE))}
                className="hover:text-ink-100 disabled:opacity-40"
              >
                ← Newer
              </button>
              <span>
                {offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total.toLocaleString()}
              </span>
              <button
                disabled={offset + PAGE >= data.total}
                onClick={() => setOffset(offset + PAGE)}
                className="hover:text-ink-100 disabled:opacity-40"
              >
                Older →
              </button>
            </div>
          )}
        </Panel>
        <p className="text-ink-500 text-[11px]">
          Sources: U.S. Treasury OFAC SDN list; Federal Register (Department of State notices). U.S.
          government works.
        </p>
      </div>
    </div>
  )
}
