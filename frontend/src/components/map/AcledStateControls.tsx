import type { AcledOrigin, AcledWeeklyMeta } from '../../api/types'
import { ACLED_EVENT_TYPES, ACLED_STATE_COLORS } from '../../lib/acledWeekly'
import { breakLabels } from '../../lib/choropleth'

export interface AcledStateSelection {
  eventType: string // '' = all types
  week: string // Saturday that starts the last week of the period
  span: 4 | 13 | 52
}

const SPANS = [
  { value: 4, label: '4 weeks' },
  { value: 13, label: '13 weeks' },
  { value: 52, label: '52 weeks' },
] as const

const INPUT =
  'border-ink-700 bg-ink-950 text-ink-100 w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none'

interface Props {
  meta: AcledWeeklyMeta
  value: AcledStateSelection
  onChange: (v: AcledStateSelection) => void
  breaks: number[]
  period: string
  origins: AcledOrigin[]
  states: number | null
  loading: boolean
  error: string | null
}

/** Event type and week range for the ACLED-by-state choropleth (ADR 0011). */
export default function AcledStateControls({ meta, value, onChange, breaks, ...state }: Props) {
  const mixed = state.origins.length > 1
  const fromAggregates = state.origins.includes('aggregate')
  return (
    <div className="mt-2 space-y-2 pl-6">
      <select
        aria-label="ACLED event type"
        value={value.eventType}
        onChange={(e) => onChange({ ...value, eventType: e.target.value })}
        className={INPUT}
      >
        <option value="">All event types</option>
        {ACLED_EVENT_TYPES.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <div className="grid grid-cols-[1fr_auto] gap-2">
        <input
          type="date"
          aria-label="Last week"
          max={meta.aggregate_last_week ?? meta.horizon_week_end ?? undefined}
          value={value.week}
          onChange={(e) => e.target.value && onChange({ ...value, week: e.target.value })}
          className={INPUT}
        />
        <select
          aria-label="ACLED period"
          value={value.span}
          onChange={(e) => onChange({ ...value, span: Number(e.target.value) as 4 | 13 | 52 })}
          className={INPUT}
        >
          {SPANS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      <p className="text-ink-300 text-[11px]">{state.period}</p>
      {state.error ? (
        <p className="text-xs text-amber-400">{state.error}</p>
      ) : (
        <>
          <ul className="space-y-0.5 text-[11px]">
            {breakLabels(breaks).map((label, i) => (
              <li key={label} className="flex items-center gap-2">
                <span
                  className="h-2.5 w-4 rounded-sm"
                  style={{ background: ACLED_STATE_COLORS[i] }}
                />
                <span className="text-ink-300 tabular-nums">{label} events</span>
              </li>
            ))}
          </ul>
          <p className="text-ink-500 text-[11px] leading-relaxed">
            {state.loading ? 'Loading…' : `${state.states ?? 0} states with events`}.{' '}
            {fromAggregates
              ? mixed
                ? 'Combines ACLED event records with ACLED weekly aggregates (state totals).'
                : 'From ACLED weekly aggregates: state totals, no individual events.'
              : 'From ACLED event records.'}{' '}
            Weeks run Saturday to Friday. Source: ACLED, acleddata.com.
          </p>
        </>
      )}
    </div>
  )
}
