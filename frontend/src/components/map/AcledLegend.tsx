import { EVENT_TYPE_COLORS } from './eventColors'

interface Props {
  accessed: string | null
  filters: string
  mode: 'heat' | 'points'
}

/**
 * Legend + ACLED attribution on the visual itself, as ACLED's Attribution Policy requires:
 * source name, link, access date, and the filters applied.
 */
export default function AcledLegend({ accessed, filters, mode }: Props) {
  return (
    <div
      aria-label="Event legend and attribution"
      className="border-ink-700 bg-ink-900/90 absolute bottom-8 left-3 z-10 max-w-sm rounded-md border px-3 py-2 text-[11px] shadow-lg backdrop-blur"
    >
      {mode === 'points' ? (
        <ul className="mb-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5">
          {Object.entries(EVENT_TYPE_COLORS).map(([type, color]) => (
            <li key={type} className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full" style={{ background: color }} />
              <span className="text-ink-300 truncate">{type}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="mb-1.5 flex items-center gap-2">
          <span className="text-ink-500">Density</span>
          <span
            className="h-2 w-28 rounded"
            style={{ background: 'linear-gradient(90deg,#4c1d95,#be123c,#f97316,#fde68a)' }}
          />
          <span className="text-ink-500">weighted by fatalities</span>
        </div>
      )}
      <p className="text-ink-300 leading-snug">
        Events: ACLED (Armed Conflict Location &amp; Event Data),{' '}
        <a
          href="https://acleddata.com"
          target="_blank"
          rel="noreferrer noopener"
          className="underline"
        >
          acleddata.com
        </a>
        {accessed ? `, accessed ${accessed}` : ''}. Filtered: {filters}.
      </p>
    </div>
  )
}
