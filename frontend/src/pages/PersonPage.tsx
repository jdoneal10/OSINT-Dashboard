import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { usePerson, usePersonMutations } from '../api/hooks'
import type { PersonClaim } from '../api/types'
import Panel from '../components/news/Panel'
import AdmiraltyBadge from '../components/news/AdmiraltyBadge'
import { CLAIM_KIND_LABELS, roleLabel } from '../lib/persons'
import { Chip } from './PersonsPage'

const KIND_ORDER = ['role', 'organization', 'alias', 'title', 'status', 'nationality', 'event']

function claimValue(c: PersonClaim): string {
  if (c.kind === 'role' || c.kind === 'status') return roleLabel(c.value)
  if (c.kind === 'organization') {
    const [role, org] = c.value.split(': ', 2)
    return `${org} (${roleLabel(role)})`
  }
  if (c.kind === 'event') return `${roleLabel(c.value)}${c.event_date ? ` · ${c.event_date}` : ''}`
  return c.value
}

/** One person record: every claim with its citation, shown as reported (ADR 0013). */
export default function PersonPage() {
  const params = useParams()
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const id = params.id ? Number(params.id) : null
  const includeUs = search.get('us') === '1'
  const { data, isPending, error } = usePerson(id, includeUs)
  const { dispute, remove, undo, clearDistinct } = usePersonMutations()
  const [note, setNote] = useState('')
  const [confirming, setConfirming] = useState(false)

  if (isPending) return <p className="text-ink-500 p-6 text-xs">Loading…</p>
  if (error || !data)
    return (
      <div className="space-y-2 p-6 text-xs">
        <p className="text-ink-300">
          Person not found. Records reported as U.S. persons are hidden unless included from the
          People list.
        </p>
        <Link to="/persons" className="text-sky-400 hover:underline">
          ← People
        </Link>
      </div>
    )

  const merged = data.records.length > 1
  const claims = [...data.claims].sort(
    (a, b) =>
      KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) ||
      b.citation.reported_on.localeCompare(a.citation.reported_on),
  )

  return (
    <div className="h-full overflow-y-auto px-6 py-4">
      <div className="mx-auto max-w-5xl space-y-4">
        <Link to="/persons" className="text-xs text-sky-400 hover:underline">
          ← People
        </Link>
        <header>
          <h1 className="text-ink-100 text-lg font-semibold">
            {data.display_name}
            {data.disputed && <Chip tone="rose">disputed</Chip>}
            {data.us_person && <Chip tone="amber">U.S. person</Chip>}
          </h1>
          <p className="text-ink-500 text-xs">
            {data.roles.map(roleLabel).join(', ')}
            {data.organizations.length > 0 && ` · ${data.organizations.join(', ')}`} ·{' '}
            {data.n_sources} outlet{data.n_sources === 1 ? '' : 's'}, {data.n_documents} article
            {data.n_documents === 1 ? '' : 's'}
          </p>
        </header>
        <p className="border-ink-700 bg-ink-900 text-ink-300 rounded border px-3 py-2 text-xs">
          Everything below is <b>as reported</b> by the cited source on the date shown, with that
          source&apos;s Admiralty grade. It is not an established fact or a finding about this
          person.
        </p>
        {data.disputed && data.dispute_note && (
          <p className="rounded border border-rose-800/60 bg-rose-950/30 px-3 py-2 text-xs text-rose-200">
            Disputed: {data.dispute_note}
          </p>
        )}

        {merged && (
          <Panel title="Merged records" aside={`${data.records.length} merged by you`}>
            <p className="text-ink-500 mb-2 text-xs">
              The heading uses the name published by {data.records[0].sources.join(', ')}. The other
              sources published only the names shown against them.
            </p>
            <ul className="divide-ink-800 divide-y text-xs">
              {data.records.map((r) => (
                <li key={r.id} className="flex flex-wrap items-baseline gap-2 py-1.5">
                  <span className="text-ink-100">{r.display_name}</span>
                  <span className="text-ink-500">
                    #{r.id} · {r.sources.join(', ')}
                  </span>
                  {r.merge_id !== null && (
                    <button
                      className="ml-auto text-sky-400 hover:underline"
                      aria-label={`Undo merge of record ${r.id}`}
                      disabled={undo.isPending}
                      onClick={() => undo.mutate(r.merge_id as number)}
                    >
                      Undo merge
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </Panel>
        )}
        {data.distinct_from.length > 0 && (
          <Panel title="Marked not the same person">
            <ul className="space-y-1 text-xs">
              {data.distinct_from.map((d) => (
                <li key={d.id} className="flex gap-2">
                  <Link to={`/persons/${d.person_id}`} className="text-sky-400 hover:underline">
                    {d.display_name} #{d.person_id}
                  </Link>
                  <button
                    className="text-ink-300 ml-auto hover:underline"
                    disabled={clearDistinct.isPending}
                    onClick={() => clearDistinct.mutate(d.id)}
                  >
                    Undo
                  </button>
                </li>
              ))}
            </ul>
          </Panel>
        )}

        <Panel title="Claims" aside={`${claims.length} cited`}>
          <table className="w-full text-left text-xs">
            <thead className="text-ink-500">
              <tr>
                <th className="py-1 pr-3 font-medium">Claim</th>
                <th className="py-1 pr-3 font-medium">Value</th>
                {merged && <th className="py-1 pr-3 font-medium">Named as</th>}
                <th className="py-1 pr-3 font-medium">Source</th>
                <th className="py-1 pr-3 font-medium">Reported</th>
                <th className="py-1 pr-3 font-medium">Grade</th>
                <th className="py-1 font-medium">Evidence</th>
              </tr>
            </thead>
            <tbody className="divide-ink-800 divide-y">
              {claims.map((c, i) => (
                <tr key={`${c.kind}-${c.value}-${i}`} className="align-top">
                  <td className="text-ink-500 py-1.5 pr-3 whitespace-nowrap">
                    {CLAIM_KIND_LABELS[c.kind] ?? c.kind}
                  </td>
                  <td className="text-ink-100 py-1.5 pr-3">{claimValue(c)}</td>
                  {merged && <td className="text-ink-300 py-1.5 pr-3">{c.reported_name}</td>}
                  <td className="py-1.5 pr-3">
                    {c.citation.document_id ? (
                      <Link
                        to={`/news/${c.citation.document_id}`}
                        className="text-sky-400 hover:underline"
                      >
                        {c.citation.source}
                      </Link>
                    ) : (
                      <span className="text-ink-300">{c.citation.source}</span>
                    )}
                  </td>
                  <td className="text-ink-300 py-1.5 pr-3 whitespace-nowrap tabular-nums">
                    {c.citation.reported_on}
                  </td>
                  <td className="py-1.5 pr-3">
                    <AdmiraltyBadge grade={c.citation.grade} />
                  </td>
                  <td className="text-ink-500 py-1.5 italic">
                    {c.citation.evidence ? `“${c.citation.evidence}”` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Owner control">
          <div className="space-y-3 text-xs">
            <div className="flex flex-wrap items-end gap-2">
              {!data.disputed && (
                <input
                  aria-label="Dispute note"
                  placeholder="Why is this record disputed? (optional)"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  className="border-ink-700 bg-ink-800 text-ink-100 w-96 rounded border px-2 py-1 focus:border-sky-500 focus:outline-none"
                />
              )}
              <button
                onClick={() =>
                  dispute.mutate({ id: data.id, disputed: !data.disputed, note: note || null })
                }
                disabled={dispute.isPending}
                className="border-ink-700 text-ink-100 hover:border-ink-500 rounded border px-2 py-1"
              >
                {data.disputed ? 'Clear dispute' : 'Mark disputed'}
              </button>
              {confirming ? (
                <>
                  <span className="text-rose-300">
                    Delete this record{merged && ` (all ${data.records.length} merged records)`} and
                    all {claims.length} claims? This cannot be undone.
                  </span>
                  <button
                    onClick={() =>
                      remove.mutate(data.id, { onSuccess: () => navigate('/persons') })
                    }
                    className="rounded border border-rose-700 px-2 py-1 text-rose-200 hover:bg-rose-950"
                  >
                    Delete
                  </button>
                  <button
                    onClick={() => setConfirming(false)}
                    className="text-ink-500 hover:text-ink-100 px-1"
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <button
                  onClick={() => setConfirming(true)}
                  className="rounded border border-rose-800/60 px-2 py-1 text-rose-300 hover:border-rose-600"
                >
                  Delete record…
                </button>
              )}
            </div>
            <p className="text-ink-500">
              Disputed records stay visible and labeled. Deleting removes the record and every claim
              and link; re-extracting its documents can create it again.
            </p>
          </div>
        </Panel>
      </div>
    </div>
  )
}
