import { useHealth } from '../api/hooks'

function ago(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  return mins < 1 ? 'just now' : mins < 60 ? `${mins}m ago` : `${Math.round(mins / 60)}h ago`
}

export default function HealthIndicator() {
  const { data, isError, isPending } = useHealth()

  let tone = 'bg-ink-500'
  let label = 'Checking API…'
  let detail = ''
  if (isError) {
    tone = 'bg-rose-500'
    label = 'API offline'
  } else if (data) {
    tone = data.status === 'ok' ? 'bg-emerald-500' : 'bg-amber-500'
    label = data.status === 'ok' ? 'API ok' : 'API degraded'
    detail = [
      data.postgis_version && `PostGIS ${data.postgis_version}`,
      data.worker_last_heartbeat ? `worker ${ago(data.worker_last_heartbeat)}` : 'worker idle',
    ]
      .filter(Boolean)
      .join(' · ')
  }

  return (
    <div role="status" aria-live="polite" className="text-ink-300 flex items-center gap-2 text-xs">
      <span className={`h-2 w-2 rounded-full ${tone} ${isPending ? 'animate-pulse' : ''}`} />
      <span className="text-ink-100">{label}</span>
      {detail && <span className="text-ink-500 hidden md:inline">{detail}</span>}
    </div>
  )
}
