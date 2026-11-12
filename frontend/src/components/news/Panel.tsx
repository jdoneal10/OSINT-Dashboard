import type { ReactNode } from 'react'

export default function Panel({
  title,
  aside,
  children,
  className = '',
}: {
  title: string
  aside?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`border-ink-700 bg-ink-900 rounded-md border ${className}`}>
      <header className="border-ink-700 flex items-baseline justify-between gap-3 border-b px-4 py-2">
        <h2 className="text-ink-100 text-xs font-semibold tracking-wide uppercase">{title}</h2>
        {aside && <div className="text-ink-500 text-xs">{aside}</div>}
      </header>
      <div className="px-4 py-3">{children}</div>
    </section>
  )
}
