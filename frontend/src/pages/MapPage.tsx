import { useEffect, useMemo, useState } from 'react'
import { useAoi, useEventPoints, useEventTypes, useEventsMeta, useNodes } from '../api/hooks'
import LayerPanel from '../components/LayerPanel'
import AcledLegend from '../components/map/AcledLegend'
import { basemapAvailable } from '../components/map/basemap'
import EventDetailCard from '../components/map/EventDetailCard'
import EventFilters from '../components/map/EventFilters'
import OperationalMap, {
  type EventMode,
  type LayerVisibility,
} from '../components/map/OperationalMap'
import { useDebounced } from '../hooks/useDebounced'
import { describeFilters, eventFilterParams, type EventFilterState } from '../lib/eventFilters'
import { localDate } from '../lib/dates'
import { toMonth } from '../lib/months'

const FALLBACK_BOUNDS: [string, string] = ['2018-01', toMonth(new Date().toISOString())]

export default function MapPage() {
  const aoi = useAoi(1)
  const nodes = useNodes()
  const meta = useEventsMeta()
  const types = useEventTypes()
  const [basemap, setBasemap] = useState<boolean | null>(null)
  const [visibility, setVisibility] = useState<LayerVisibility>({
    aoi: true,
    poe: true,
    events: true,
  })
  const [mode, setMode] = useState<EventMode>('heat')
  const [selected, setSelected] = useState<number | null>(null)

  const bounds: [string, string] = meta.data?.min_date
    ? [toMonth(meta.data.min_date), toMonth(meta.data.max_date ?? meta.data.min_date)]
    : FALLBACK_BOUNDS
  const [filters, setFilters] = useState<EventFilterState | null>(null)
  const [lo, hi] = bounds
  const active: EventFilterState = useMemo(
    () => filters ?? { startMonth: lo, endMonth: hi, eventTypes: [], actors: [] },
    [filters, lo, hi],
  )
  const params = useDebounced(
    useMemo(() => eventFilterParams(active), [active]),
    200,
  )
  const points = useEventPoints(params, meta.isSuccess && (meta.data?.total ?? 0) > 0)

  useEffect(() => {
    let live = true
    basemapAvailable().then((ok) => live && setBasemap(ok))
    return () => {
      live = false
    }
  }, [])

  const error = aoi.error ?? nodes.error ?? meta.error
  const noEvents = meta.isSuccess && meta.data.total === 0

  return (
    <div className="flex h-full">
      <LayerPanel
        aoi={aoi.data}
        nodes={nodes.data}
        basemap={basemap}
        visibility={visibility}
        onToggle={(k) => setVisibility((v) => ({ ...v, [k]: !v[k] }))}
      >
        {noEvents ? (
          <p className="text-ink-500 text-xs leading-relaxed">
            No events loaded yet. Run{' '}
            <code className="font-mono">make ingest SOURCE=acled SINCE=2018-01-01</code>.
          </p>
        ) : (
          <EventFilters
            bounds={bounds}
            types={types.data ?? []}
            value={active}
            onChange={setFilters}
            mode={mode}
            onModeChange={setMode}
            shown={points.data ? points.data.features.length : null}
            truncated={points.data?.truncated ?? false}
          />
        )}
      </LayerPanel>
      <div className="relative min-w-0 flex-1">
        {basemap !== null && (
          <OperationalMap
            aoi={aoi.data}
            nodes={nodes.data}
            events={points.data}
            eventMode={mode}
            basemap={basemap}
            visibility={visibility}
            onEventClick={(id) => {
              setSelected(id)
            }}
          />
        )}
        {selected !== null && <EventDetailCard id={selected} onClose={() => setSelected(null)} />}
        {visibility.events && !noEvents && (
          <AcledLegend
            accessed={localDate(meta.data?.accessed)}
            filters={describeFilters(active, types.data?.length ?? 0)}
            mode={mode}
          />
        )}
        {mode === 'heat' && visibility.events && !noEvents && (
          <div className="bg-ink-900/90 text-ink-300 absolute top-3 left-1/2 z-10 -translate-x-1/2 rounded px-2 py-1 text-xs">
            Switch to <b>points</b> to inspect individual events
          </div>
        )}
        {error && (
          <div className="absolute top-12 left-1/2 -translate-x-1/2 rounded bg-rose-950/90 px-3 py-1.5 text-xs text-rose-200 shadow">
            Data unavailable: {error.message}
          </div>
        )}
      </div>
    </div>
  )
}
