import { useLLMUsage } from '../api/hooks'
import { usd } from '../lib/format'

/** Month-to-date Claude API spend against the cap; warns at the pause threshold. */
export default function BudgetIndicator() {
  const { data, isError } = useLLMUsage()
  if (isError || !data) return null
  const share = data.cap_usd > 0 ? Math.min(data.spent_usd / data.cap_usd, 1) : 0
  const pauseAt = data.cap_usd > 0 ? data.pause_threshold_usd / data.cap_usd : 0.8
  const tone = data.paused ? 'bg-rose-500' : share >= pauseAt * 0.75 ? 'bg-amber-500' : 'bg-sky-500'
  const title = [
    `Claude API spend this month: ${usd(data.spent_usd, 4)} of ${usd(data.cap_usd)} cap`,
    `API stages pause at ${usd(data.pause_threshold_usd)}`,
    `${data.calls} calls, ${data.failed_calls} retried or failed, ${data.quarantined} quarantined`,
  ].join('\n')
  return (
    <div
      role="status"
      aria-label="LLM budget"
      title={title}
      className="text-ink-300 flex items-center gap-2 text-xs"
    >
      <span className="text-ink-500 hidden lg:inline">LLM budget</span>
      <span className="bg-ink-700 relative h-1.5 w-20 overflow-hidden rounded">
        <span
          className={`absolute inset-y-0 left-0 ${tone}`}
          style={{ width: `${share * 100}%` }}
        />
        <span
          className="absolute inset-y-0 w-px bg-rose-400/80"
          style={{ left: `${pauseAt * 100}%` }}
        />
      </span>
      <span className="text-ink-100 tabular-nums">
        {usd(data.spent_usd)} / {usd(data.cap_usd, 0)}
      </span>
      {data.paused && <span className="font-semibold text-rose-400">API paused</span>}
    </div>
  )
}
