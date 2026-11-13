import { useEffect, useMemo, useState } from 'react'
import {
  useAoi,
  useCrime,
  useCrimeMeta,
  useEventPoints,
  useEventTypes,
  useEventsMeta,
  useMunicipalities,
  useNodes,
} from '../api/hooks'
import CrimeControls, { type CrimeSelection } from '../components/map/CrimeControls'
import LayerPanel from '../components/LayerPanel'
import AcledLegend from '../components/map/AcledLegend'
import { basemapAvailable } from '../components/map/basemap'
import EventDetailCard from '../components/map/EventDetailCard'
import EventFilters from '../components/map/EventFilters'
import OperationalMap, {
  type CrimeLayer,
  type EventMode,
  type LayerVisibility,
} from '../components/map/OperationalMap'
import { useDebounced } from '../hooks/useDebounced'
import { crimeWindow, joinValues, quantileBreaks } from '../lib/choropleth'
import {
  describeFilters,
  eventFilterParams,
  includesAcled,
  includesNews,
  type EventFilterState,
} from '../lib/eventFilters'
import { localDate } from '../lib/dates'
import { toMonth } from '../lib/months'

const FALLBACK_BOUNDS: [string, string] = ['2018-01', toMonth(new Date().toISOString())]

export default function MapPage() {
  const aoi = useAoi(2)
  const nodes = useNodes()
  const meta = useEventsMeta()
  const types = useEventTypes()
  const [basemap, setBasemap] = useState<boolean | null>(null)
  const [visibility, setVisibility] = useState<LayerVisibility>({
    aoi: true,
    poe: true,
    events: true,
    crime: false,
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
  const eventSources = meta.data?.sources
  const params = useDebounced(
    useMemo(() => eventFilterParams(active, eventSources), [active, eventSources]),
    200,
  )
  const points = useEventPoints(params, meta.isSuccess && (meta.data?.total ?? 0) > 0)

  const crimeMeta = useCrimeMeta()
  const latest = crimeMeta.data
    ?.map((m) => m.last_month.slice(0, 7))
    .sort()
    .at(-1)
  const [crimeSel, setCrimeSel] = useState<CrimeSelection | null>(null)
  const crimeActive: CrimeSelection | null =
    crimeSel ?? (latest ? { crimeType: 'Homicidio', month: latest, span: 3 } : null)
  const municipalities = useMunicipalities(visibility.crime)
  const window_ =
    crimeActive && crimeMeta.data
      ? crimeWindow(crimeActive.month, crimeActive.span, crimeMeta.data)
      : null
  const crime = useCrime(
    {
      crime_type: crimeActive?.crimeType,
      start: window_ ? `${window_.start}-01` : undefined,
      end: window_ ? `${window_.end}-01` : undefined,
    },
    visibility.crime && window_ !== null,
  )
  const crimeLayer: CrimeLayer | undefined = useMemo(() => {
    if (!municipalities.data || !crime.data) return undefined
    return {
      data: joinValues(municipalities.data, crime.data),
      breaks: quantileBreaks(crime.data.items.map((i) => i.value)),
      label: `${crime.data.crime_type}, ${crime.data.start.slice(0, 7)}`,
    }
  }, [municipalities.data, crime.data])

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
        crimeControls={
          crimeMeta.data && crimeActive ? (
            <CrimeControls
              meta={crimeMeta.data}
              value={crimeActive}
              onChange={setCrimeSel}
              breaks={crimeLayer?.breaks ?? []}
              municipalities={crime.data?.items.length ?? null}
              loading={municipalities.isFetching || crime.isFetching}
              error={crime.error?.message ?? municipalities.error?.message ?? null}
              period={
                window_
                  ? window_.start === window_.end
                    ? window_.end
                    : `${window_.start} to ${window_.end}`
                  : null
              }
              clamped={window_?.clamped ?? false}
            />
          ) : (
            <p className="text-ink-500 pl-6 text-xs">
              No SESNSP data. Import with{' '}
              <code className="font-mono">make ingest SOURCE=sesnsp</code>.
            </p>
          )
        }
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
            crime={visibility.crime ? crimeLayer : undefined}
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
            acled={includesAcled(active)}
            news={includesNews(active)}
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
