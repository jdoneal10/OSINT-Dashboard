import type { ReactNode } from 'react'
import ClassificationBanner from './ClassificationBanner'
import HealthIndicator from './HealthIndicator'

/** Root layout. Every page renders inside it, so no view can appear without the banners. */
export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full flex-col">
      <ClassificationBanner position="top" />
      <header className="border-ink-700 bg-ink-900 flex shrink-0 items-center justify-between border-b px-4 py-2.5">
        <div className="flex items-baseline gap-3">
          <h1 className="text-ink-100 text-sm font-semibold tracking-wide">
            Cartel OSINT Dashboard
          </h1>
          <span className="text-ink-500 hidden text-xs sm:inline">
            TCO activity · Central America → U.S. Southwest Border
          </span>
        </div>
        <HealthIndicator />
      </header>
      <main className="min-h-0 flex-1">{children}</main>
      <ClassificationBanner position="bottom" />
    </div>
  )
}
