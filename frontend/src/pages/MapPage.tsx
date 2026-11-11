import { useEffect, useState } from 'react'
import { useAoi, useNodes } from '../api/hooks'
import LayerPanel from '../components/LayerPanel'
import { basemapAvailable } from '../components/map/basemap'
import OperationalMap, { type LayerVisibility } from '../components/map/OperationalMap'

export default function MapPage() {
  const aoi = useAoi(1)
  const nodes = useNodes()
  const [basemap, setBasemap] = useState<boolean | null>(null)
  const [visibility, setVisibility] = useState<LayerVisibility>({ aoi: true, poe: true })

  useEffect(() => {
    let live = true
    basemapAvailable().then((ok) => live && setBasemap(ok))
    return () => {
      live = false
    }
  }, [])

  const error = aoi.error ?? nodes.error

  return (
    <div className="flex h-full">
      <LayerPanel
        aoi={aoi.data}
        nodes={nodes.data}
        basemap={basemap}
        visibility={visibility}
        onToggle={(k) => setVisibility((v) => ({ ...v, [k]: !v[k] }))}
      />
      <div className="relative min-w-0 flex-1">
        {basemap !== null && (
          <OperationalMap
            aoi={aoi.data}
            nodes={nodes.data}
            basemap={basemap}
            visibility={visibility}
          />
        )}
        {error && (
          <div className="absolute top-3 left-1/2 -translate-x-1/2 rounded bg-rose-950/90 px-3 py-1.5 text-xs text-rose-200 shadow">
            Reference layers unavailable: {error.message}
          </div>
        )}
      </div>
    </div>
  )
}
