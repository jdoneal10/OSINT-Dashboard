import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { EventDetail, SeizureRecord } from '../../api/types'
import { GEO_PRECISION, quantity } from '../../lib/format'
import { eventColor } from '../map/eventColors'

const TH = 'text-ink-500 px-2 py-1.5 text-left text-[10px] font-semibold tracking-wider uppercase'
const TD = 'border-ink-700 border-t px-2 py-2 align-top'

function OutsideAoi() {
  return (
    <span className="ml-1 rounded border border-amber-500/40 px-1 text-[10px] text-amber-300">
      outside AOI
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
