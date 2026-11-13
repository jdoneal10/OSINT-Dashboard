/** ACLED attribution for views that show ACLED-corroborated reporting (Attribution Policy). */
export default function AcledAttribution({ className = '' }: { className?: string }) {
  return (
    <p className={`text-ink-500 text-[11px] leading-relaxed ${className}`}>
      Corroboration includes data from ACLED (Armed Conflict Location &amp; Event Data),{' '}
      <a
        href="https://acleddata.com"
        target="_blank"
        rel="noreferrer noopener"
        className="underline"
      >
        acleddata.com
      </a>
      , matched to news reports by municipality, date (±1 day) and event type.
    </p>
  )
}
