import { BORDER_THREATS, threatLabel } from '../../lib/threats'

export default function ThreatChip({ threat }: { threat: string }) {
  return (
    <span
      className={`rounded border px-1 text-[11px] font-medium ${
        BORDER_THREATS[threat]?.tone ?? 'border-ink-700 text-ink-300'
      }`}
    >
      {threatLabel(threat)}
    </span>
  )
}
