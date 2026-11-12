import { Link } from 'react-router'
import type { DocumentSummary } from '../../api/types'
import { dateTime } from '../../lib/format'
import AdmiraltyBadge from './AdmiraltyBadge'

const STATUS: Record<string, string> = {
  extracted: 'Extracted',
  filtered_out: 'Filtered out',
  relevant: 'Awaiting extraction',
  batched: 'In extraction batch',
  quarantined: 'Quarantined',
  new: 'Awaiting filter',
  skipped: 'Skipped',
}

export default function DocumentHeader({ doc }: { doc: DocumentSummary }) {
  const sources = Math.max(0, ...doc.clusters.map((c) => c.n_independent_sources))
  return (
    <header className="space-y-1.5">
      <div className="text-ink-500 flex flex-wrap items-center gap-2 text-xs">
        <AdmiraltyBadge grade={doc.admiralty} sources={sources} size="md" />
        <span className="text-ink-100 font-medium">{doc.source.name}</span>
        <span title="Source reliability">({doc.source.reliability})</span>
        <span>·</span>
        <span>{dateTime(doc.published_at ?? doc.retrieved_at)}</span>
        <span className="border-ink-700 rounded border px-1.5">
          {STATUS[doc.status] ?? doc.status}
        </span>
        {doc.duplicate_of_id && (
          <Link to={`/news/${doc.duplicate_of_id}`} className="text-amber-300 hover:underline">
            Copy of document {doc.duplicate_of_id}
          </Link>
        )}
      </div>
      <h1 className="text-ink-100 text-lg leading-snug font-semibold">
        {doc.title ?? `Document ${doc.id}`}
      </h1>
      {doc.url && (
        <a
          href={doc.url}
          target="_blank"
          rel="noreferrer noopener"
          className="block truncate text-xs text-sky-400 hover:underline"
        >
          {doc.url}
        </a>
      )}
    </header>
  )
}
