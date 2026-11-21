import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { DocPerson, EventDetail, SeizureRecord } from '../../api/types'
import { GEO_PRECISION, quantity } from '../../lib/format'
import { CLAIM_KIND_LABELS, roleLabel } from '../../lib/persons'
import { categoryLabel } from '../../lib/priority'
import { eventColor } from '../map/eventColors'
import ThreatChip from './ThreatChip'

const TH = 'text-ink-500 px-2 py-1.5 text-left text-[10px] font-semibold tracking-wider uppercase'
const TD = 'border-ink-700 border-t px-2 py-2 align-top'

function OutsideAoi() {
  return (
    <span className="ml-1 rounded border border-amber-500/40 px-1 text-[10px] text-amber-300">
      outside AOI
    </span>
  )
}

function LowPriority() {
  return (
    <span
      className="text-ink-400 border-ink-500/60 ml-1 rounded border px-1 text-[10px]"
      title="Small drug amount or contraband goods (owner priority framework)"
    >
      low priority
    </span>
  )
}

/** News events use perpetrator/target; ACLED events keep ACLED's actor1/actor2 dyad. */
const ROLE_PAIRS: Record<string, [string, string]> = {
  news: ['perpetrator', 'target'],
  acled: ['actor1', 'actor2'],
}

function actorsByRole(ev: EventDetail, role: string): string {
  return (
    ev.actors
      .filter((a) => a.role === role)
      .map((a) => a.name)
      .join(', ') || '—'
  )
}

/** UxS or electricity-theft detail (extract-v7; ADR 0009), as reported. */
export function PriorityDetail({ ev }: { ev: EventDetail }) {
  const chips: string[] = []
  let tag = ''
  if (ev.uxs_activity) {
    tag = 'UxS'
    chips.push(
      categoryLabel(ev.uxs_activity),
      categoryLabel(ev.uxs_platform ?? 'unknown'),
      ...(ev.uxs_missions ?? []).map(categoryLabel),
      ...(ev.uxs_payloads ?? []).map(categoryLabel),
    )
  } else if (ev.energy_method) {
    tag = 'Electricity theft'
    chips.push(
      categoryLabel(ev.energy_method),
      ...(ev.energy_powered ?? []).map(categoryLabel),
      categoryLabel(ev.energy_facilitator ?? 'none_reported'),
      ...(ev.energy_scale ? [ev.energy_scale] : []),
    )
  }
  if (!tag) return null
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      <span className="rounded border border-violet-500/50 px-1 text-[10px] text-violet-300">
        {tag}
      </span>
      {chips.map((c, i) => (
        <span key={`${c}-${i}`} className="bg-ink-800 text-ink-300 rounded px-1 text-[10px]">
          {c}
        </span>
      ))}
    </div>
  )
}

export function EventsTable({
  events,
  actions,
}: {
  events: EventDetail[]
  /** Extra cell per row (labeling controls). */
  actions?: (ev: EventDetail) => ReactNode
}) {
  if (events.length === 0) return <p className="text-ink-500 text-xs">No events extracted.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr>
            <th className={TH}>Event</th>
            <th className={TH}>Where</th>
            <th className={TH}>Fatalities</th>
            <th className={TH}>Perpetrators / targets</th>
            <th className={TH}>Cluster</th>
            {actions && <th className={TH}>Label</th>}
          </tr>
        </thead>
        <tbody>
          {events.map((ev) => (
            <tr key={ev.id}>
              <td className={`${TD} w-[38%]`}>
                <div className="flex items-center gap-1.5 font-medium">
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ background: eventColor(ev.event_type) }}
                  />
                  {ev.event_type}
                  {ev.source === 'acled' && (
                    <span className="rounded border border-sky-500/40 px-1 text-[10px] font-normal text-sky-300">
                      ACLED {ev.source_key}
                    </span>
                  )}
                  {ev.sub_event_type && (
                    <span className="text-ink-500 font-normal">· {ev.sub_event_type}</span>
                  )}
                </div>
                <div className="text-ink-500">{ev.event_date}</div>
                {ev.border_threat && (
                  <div className="mt-0.5">
                    <ThreatChip threat={ev.border_threat} />
                  </div>
                )}
                <PriorityDetail ev={ev} />
                {ev.description && <p className="text-ink-300 mt-1">{ev.description}</p>}
                {ev.evidence && (
                  <blockquote className="border-ink-700 text-ink-500 mt-1 border-l-2 pl-2 italic">
                    “{ev.evidence}”
                  </blockquote>
                )}
              </td>
              <td className={TD}>
                {[ev.location_name, ev.admin2_name, ev.admin1_name].filter(Boolean).join(', ') ||
                  '—'}
                {!ev.in_aoi && <OutsideAoi />}
                <div className="text-ink-500">
                  {ev.geo_precision
                    ? `${GEO_PRECISION[ev.geo_precision]} precision`
                    : 'not geocoded'}
                </div>
              </td>
              <td className={`${TD} tabular-nums`}>{ev.fatalities ?? '—'}</td>
              <td className={TD}>
                {(() => {
                  const [a, b] = ROLE_PAIRS[ev.source === 'acled' ? 'acled' : 'news']
                  return (
                    <>
                      <div>{actorsByRole(ev, a)}</div>
                      <div className="text-ink-500">
                        {ev.source === 'acled' ? 'vs' : '→'} {actorsByRole(ev, b)}
                      </div>
                    </>
                  )
                })()}
              </td>
              <td className={TD}>
                {ev.cluster_id ? (
                  <Link to={`/clusters/${ev.cluster_id}`} className="text-sky-400 hover:underline">
                    #{ev.cluster_id}
                  </Link>
                ) : (
                  '—'
                )}
              </td>
              {actions && <td className={TD}>{actions(ev)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function SeizuresTable({
  seizures,
  actions,
}: {
  seizures: SeizureRecord[]
  actions?: (s: SeizureRecord) => ReactNode
}) {
  if (seizures.length === 0) return <p className="text-ink-500 text-xs">No seizures extracted.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr>
            <th className={TH}>Substance</th>
            <th className={TH}>Quantity</th>
            <th className={TH}>Date</th>
            <th className={TH}>Agency</th>
            <th className={TH}>Where</th>
            {actions && <th className={TH}>Label</th>}
          </tr>
        </thead>
        <tbody>
          {seizures.map((s) => (
            <tr key={s.id}>
              <td className={TD}>
                <span className="font-medium">{s.substance}</span>
                {s.low_priority && <LowPriority />}
                {s.chemical_class && <div className="text-ink-500">{s.chemical_class}</div>}
              </td>
              <td className={`${TD} tabular-nums`}>{quantity(s.quantity, s.unit)}</td>
              <td className={TD}>{s.seizure_date}</td>
              <td className={TD}>{s.seizing_agency ?? '—'}</td>
              <td className={TD}>
                {s.admin1_code ?? '—'}
                {s.node_id && <span className="text-ink-500"> · port of entry</span>}
                {!s.in_aoi && <OutsideAoi />}
              </td>
              {actions && <td className={TD}>{actions(s)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Persons extracted from one document, with that document's claims (ADR 0013). */
export function PersonsTable({
  persons,
  actions,
}: {
  persons: DocPerson[]
  actions?: (p: DocPerson) => ReactNode
}) {
  if (persons.length === 0) return <p className="text-ink-500 text-xs">No persons extracted.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr>
            <th className={TH}>Person (as reported)</th>
            <th className={TH}>Claims from this document</th>
            {actions && <th className={TH}>Label</th>}
          </tr>
        </thead>
        <tbody>
          {persons.map((p) => (
            <tr key={p.id}>
              <td className={`${TD} w-[30%]`}>
                <Link
                  to={`/persons/${p.id}${p.us_person ? '?us=1' : ''}`}
                  className="text-sky-400 hover:underline"
                >
                  {p.display_name}
                </Link>
                {p.us_person && (
                  <span className="ml-1 rounded border border-amber-500/40 px-1 text-[10px] text-amber-300">
                    U.S. person · hidden from person views
                  </span>
                )}
                {p.disputed && (
                  <span className="ml-1 rounded border border-rose-500/40 px-1 text-[10px] text-rose-300">
                    disputed
                  </span>
                )}
              </td>
              <td className={TD}>
                <ul className="space-y-0.5">
                  {p.claims.map((c, i) => (
                    <li key={`${c.kind}-${c.value}-${i}`}>
                      <span className="text-ink-500">{CLAIM_KIND_LABELS[c.kind] ?? c.kind}:</span>{' '}
                      {c.kind === 'organization'
                        ? (() => {
                            const [role, org] = c.value.split(': ', 2)
                            return `${org} (${roleLabel(role)})`
                          })()
                        : c.kind === 'role' || c.kind === 'status' || c.kind === 'event'
                          ? roleLabel(c.value)
                          : c.value}
                      {c.event_id !== null && c.kind === 'event' && (
                        <span className="text-ink-500"> · event {c.event_id}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </td>
              {actions && <td className={TD}>{actions(p)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
