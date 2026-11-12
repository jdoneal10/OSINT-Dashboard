import { CHOROPLETH_COLORS, breakLabels } from '../../lib/choropleth'
import type { CrimeMethodology } from '../../api/types'

export interface CrimeSelection {
  crimeType: string
  month: string // 'YYYY-MM', last month of the period
  span: 1 | 3 | 12
}

const SPANS = [
  { value: 1, label: '1 month' },
  { value: 3, label: '3 months' },
  { value: 12, label: '12 months' },
] as const

interface Props {
  meta: CrimeMethodology[]
  value: CrimeSelection
  onChange: (v: CrimeSelection) => void
  breaks: number[]
  municipalities: number | null
  error: string | null
  loading: boolean
  /** Period actually shown, e.g. "2026-01 to 2026-09" (clamped to one methodology). */
  period: string | null
  clamped: boolean
}

const INPUT =
  'border-ink-700 bg-ink-950 text-ink-100 w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none'

/** Crime type + month picker and legend for the SESNSP municipal choropleth. */
export default function CrimeControls({ meta, value, onChange, breaks, ...state }: Props) {
  const types = [...new Set(meta.flatMap((m) => m.crime_types))].sort()
  const first = meta.map((m) => m.first_month.slice(0, 7)).sort()[0]
  const last = meta
    .map((m) => m.last_month.slice(0, 7))
    .sort()
    .at(-1)
  const method = meta.find(
    (m) => value.month >= m.first_month.slice(0, 7) && value.month <= m.last_month.slice(0, 7),
  )
  return (
    <div className="mt-2 space-y-2 pl-6">
      <select
        aria-label="Crime type"
        value={value.crimeType}
        onChange={(e) => onChange({ ...value, crimeType: e.target.value })}
        className={INPUT}
      >
        {types.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <div className="grid grid-cols-[1fr_auto] gap-2">
        <input
          type="month"
          aria-label="Month"
          min={first}
          max={last}
          value={value.month}
          onChange={(e) => e.target.value && onChange({ ...value, month: e.target.value })}
          className={INPUT}
        />
        <select
          aria-label="Period"
          value={value.span}
          onChange={(e) => onChange({ ...value, span: Number(e.target.value) as 1 | 3 | 12 })}
          className={INPUT}
        >
          {SPANS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      {state.period && (
        <p className="text-ink-300 text-[11px]">
          {state.period}
          {state.clamped && (
            <span className="text-amber-400"> (shortened: methodology changed in 2026)</span>
          )}
        </p>
      )}
      {state.error ? (
        <p className="text-xs text-amber-400">{state.error}</p>
      ) : (
        <>
          <ul className="space-y-0.5 text-[11px]">
            {breakLabels(breaks).map((label, i) => (
              <li key={label} className="flex items-center gap-2">
                <span
                  className="h-2.5 w-4 rounded-sm"
                  style={{ background: CHOROPLETH_COLORS[i] }}
                />
                <span className="text-ink-300 tabular-nums">{label}</span>
              </li>
            ))}
          </ul>
          <p className="text-ink-500 text-[11px] leading-relaxed">
            {state.loading
              ? 'Loading…'
              : `${state.municipalities ?? 0} municipalities with reports`}
            {method && ` · ${method.methodology} methodology, snapshot ${method.snapshot_date}`}.
            Counts are crimes reported to state prosecutors (carpetas de investigación), not
            victims; 2026 figures use a new methodology and are not comparable with 2015–2025.
          </p>
        </>
      )}
    </div>
  )
}
