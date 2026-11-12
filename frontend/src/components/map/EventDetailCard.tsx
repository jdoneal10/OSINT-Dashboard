import { useEvent } from '../../api/hooks'
import { localDate } from '../../lib/dates'
import { eventColor } from './eventColors'

const GEO = { 1: 'exact location', 2: 'near location', 3: 'regional (admin-level)' } as const
const TIME = { 1: 'exact day', 2: 'within a week', 3: 'within a month' } as const
const ROLE = {
  actor1: 'Actor 1',
  actor2: 'Actor 2',
  assoc_actor1: 'Assoc. (1)',
  assoc_actor2: 'Assoc. (2)',
} as const

interface Props {
  id: number
  onClose: () => void
}

export default function EventDetailCard({ id, onClose }: Props) {
  const { data, isPending, isError } = useEvent(id)
  return (
    <section
      aria-label="Event detail"
      className="border-ink-700 bg-ink-900/95 absolute top-3 right-14 z-10 w-80 rounded-md border shadow-xl backdrop-blur"
    >
      <header className="border-ink-700 flex items-start justify-between border-b px-3 py-2">
        {data ? (
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ background: eventColor(data.event_type) }}
              />
              {data.event_type}
            </div>
            <div className="text-ink-500 text-xs">
              {data.event_date}
              {data.sub_event_type && ` · ${data.sub_event_type}`}
            </div>
          </div>
        ) : (
          <div className="text-ink-500 text-sm">
            {isError ? 'Could not load event' : 'Loading…'}
          </div>
        )}
        <button
          onClick={onClose}
          aria-label="Close event detail"
          className="text-ink-500 hover:text-ink-100 -mr-1 px-1 text-lg leading-none"
        >
          ×
        </button>
      </header>
      {data && !isPending && (
        <div className="max-h-[60vh] space-y-3 overflow-y-auto px-3 py-2 text-xs">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-ink-500">Fatalities</dt>
            <dd className="tabular-nums">{data.fatalities ?? '—'}</dd>
            <dt className="text-ink-500">Location</dt>
            <dd>
              {[data.location_name, data.admin2_name, data.admin1_name].filter(Boolean).join(', ')}
            </dd>
            <dt className="text-ink-500">Precision</dt>
            <dd>
              {GEO[data.geo_precision as keyof typeof GEO] ?? 'unknown'};{' '}
              {TIME[data.time_precision as keyof typeof TIME] ?? 'unknown'}
            </dd>
            <dt className="text-ink-500">Confidence</dt>
            <dd>{data.confidence !== null ? data.confidence.toFixed(2) : 'not assessed'}</dd>
          </dl>
          {data.actors.length > 0 && (
            <ul className="space-y-0.5">
              {data.actors.map((a) => (
                <li key={`${a.role}-${a.id}`} className="flex gap-2">
                  <span className="text-ink-500 w-16 shrink-0">
                    {ROLE[a.role as keyof typeof ROLE] ?? a.role}
                  </span>
                  <span>{a.name}</span>
                </li>
              ))}
            </ul>
          )}
          {data.description && <p className="text-ink-300 leading-relaxed">{data.description}</p>}
          <p className="text-ink-500 border-ink-700 border-t pt-2">
            Source: {data.source.toUpperCase()} event {data.source_key} · retrieved{' '}
            {localDate(data.retrieved_at)}
          </p>
        </div>
      )}
    </section>
  )
}
