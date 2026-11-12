import { NavLink, Outlet } from 'react-router'
import ClassificationBanner from './ClassificationBanner'
import HealthIndicator from './HealthIndicator'

const NAV = [
  { to: '/', label: 'Operational map', end: true },
  { to: '/border', label: 'Border panel', end: false },
]

/** Root layout route. Every page renders in its Outlet, so no view can appear without the banners. */
export default function AppShell() {
  return (
    <div className="flex h-full flex-col">
      <ClassificationBanner position="top" />
      <header className="border-ink-700 bg-ink-900 flex shrink-0 items-center justify-between border-b px-4">
        <div className="flex items-center gap-6">
          <h1 className="text-ink-100 py-2.5 text-sm font-semibold tracking-wide">
            Cartel OSINT Dashboard
          </h1>
          <nav aria-label="Views" className="flex gap-1 self-stretch">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `flex items-center border-b-2 px-3 text-xs font-medium tracking-wide ${
                    isActive
                      ? 'border-sky-400 text-ink-100'
                      : 'text-ink-500 hover:text-ink-300 border-transparent'
                  }`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <HealthIndicator />
      </header>
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
      <ClassificationBanner position="bottom" />
    </div>
  )
}
