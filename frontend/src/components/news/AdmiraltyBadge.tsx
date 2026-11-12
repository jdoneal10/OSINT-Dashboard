import { describeGrade, gradeTone } from '../../lib/admiralty'

interface Props {
  grade: string | null
  /** Independent sources behind the grade, shown as "· 2 src". */
  sources?: number
  size?: 'sm' | 'md'
}

/** Admiralty grade chip, e.g. "B2", with the meaning on hover and for screen readers. */
export default function AdmiraltyBadge({ grade, sources, size = 'sm' }: Props) {
  const label = describeGrade(grade)
  return (
    <span
      title={label}
      aria-label={`Admiralty ${grade ?? 'ungraded'}: ${label}`}
      className={`inline-flex items-center gap-1 rounded border font-mono font-semibold tabular-nums ${gradeTone(
        grade,
      )} ${size === 'md' ? 'px-2 py-0.5 text-sm' : 'px-1.5 text-[11px]'}`}
    >
      {grade ?? '—'}
      {sources !== undefined && sources > 0 && (
        <span className="font-sans font-normal opacity-80">· {sources} src</span>
      )}
    </span>
  )
}
