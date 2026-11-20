export const CLASSIFICATION_TEXT = 'UNCLASSIFIED — OPEN-SOURCE INFORMATION ONLY'

interface Props {
  position: 'top' | 'bottom'
}

/** Persistent classification marking (CLAUDE.md hard rule 7). Rendered by AppShell on every view. */
export default function ClassificationBanner({ position }: Props) {
  return (
    <div
      role="note"
      aria-label={`Classification banner (${position})`}
      data-testid={`classification-${position}`}
      className="bg-unclass shrink-0 py-0.5 text-center text-[11px] font-semibold tracking-[0.18em] text-white select-none"
    >
      {CLASSIFICATION_TEXT}
    </div>
  )
}
