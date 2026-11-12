import { fromIndex, monthIndex, monthLabel } from '../../lib/months'

interface Props {
  min: string // 'YYYY-MM'
  max: string
  value: [string, string]
  onChange: (value: [string, string]) => void
}

/** Two linked month sliders (keyboard-accessible native range inputs). */
export default function MonthRangeSlider({ min, max, value, onChange }: Props) {
  const lo = monthIndex(min)
  const hi = monthIndex(max)
  const [start, end] = value.map(monthIndex)
  const input = 'w-full accent-sky-500'
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs tabular-nums">
        <span className="text-ink-100">{monthLabel(value[0])}</span>
        <span className="text-ink-500">to</span>
        <span className="text-ink-100">{monthLabel(value[1])}</span>
      </div>
      <input
        type="range"
        aria-label="Start month"
        className={input}
        min={lo}
        max={hi}
        value={start}
        onChange={(e) => {
          const s = Number(e.target.value)
          onChange([fromIndex(s), fromIndex(Math.max(s, end))])
        }}
      />
      <input
        type="range"
        aria-label="End month"
        className={input}
        min={lo}
        max={hi}
        value={end}
        onChange={(e) => {
          const v = Number(e.target.value)
          onChange([fromIndex(Math.min(start, v)), fromIndex(v)])
        }}
      />
    </div>
  )
}
