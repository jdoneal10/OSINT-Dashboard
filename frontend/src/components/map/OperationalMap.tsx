import * as maplibregl from 'maplibre-gl'
import type { ExpressionSpecification, GeoJSONSource, LngLatBoundsLike } from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import { useEffect, useRef, useState } from 'react'
import type { AreaProps, Citation, NodeProps, ReferenceCollection } from '../../api/types'
import { basemapStyle, fallbackStyle } from './basemap'

export interface LayerVisibility {
  aoi: boolean
  poe: boolean
}

interface Props {
  aoi?: ReferenceCollection<AreaProps>
  nodes?: ReferenceCollection<NodeProps>
  basemap: boolean
  visibility: LayerVisibility
}

let protocolRegistered = false
function ensurePmtilesProtocol() {
  if (protocolRegistered) return
  maplibregl.addProtocol('pmtiles', new Protocol().tile)
  protocolRegistered = true
}

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }
const LABEL_FONT = ['Noto Sans Medium']

function toGeoJSON<P extends object>(
  fc: ReferenceCollection<P> | undefined,
  filter?: (p: P) => boolean,
): GeoJSON.FeatureCollection {
  if (!fc) return EMPTY
  const features: GeoJSON.Feature[] = []
  for (const f of fc.features) {
    // Features without public geometry (e.g. USBP sectors) are listed, not drawn.
    if (f.geometry && (!filter || filter(f.properties))) {
      features.push({ type: 'Feature', geometry: f.geometry, properties: { ...f.properties } })
    }
  }
  return { type: 'FeatureCollection', features }
}

function labelPoints(fc: ReferenceCollection<AreaProps>): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: fc.features.map((f) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: f.properties.label_point },
      properties: { name: f.properties.name },
    })),
  }
}

function boundsOf(fc: ReferenceCollection<AreaProps>): LngLatBoundsLike | null {
  const b = new maplibregl.LngLatBounds()
  const walk = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === 'number') b.extend(c as [number, number])
    else if (Array.isArray(c)) c.forEach(walk)
  }
  fc.features.forEach(
    (f) => f.geometry && 'coordinates' in f.geometry && walk(f.geometry.coordinates),
  )
  return b.isEmpty() ? null : b
}

function addOverlays(map: maplibregl.Map) {
  map.addSource('aoi', { type: 'geojson', data: EMPTY, attribution: 'Boundaries: Natural Earth' })
  map.addSource('poe', { type: 'geojson', data: EMPTY, attribution: 'Ports: BTS / CBP' })

  const byCountry: ExpressionSpecification = [
    'match',
    ['get', 'country_iso3'],
    'MEX',
    '#f59e0b',
    '#38bdf8',
  ]
  map.addLayer({
    id: 'aoi-fill',
    type: 'fill',
    source: 'aoi',
    paint: { 'fill-color': byCountry, 'fill-opacity': 0.07 },
  })
  map.addLayer({
    id: 'aoi-line',
    type: 'line',
    source: 'aoi',
    paint: { 'line-color': byCountry, 'line-width': 1.4, 'line-opacity': 0.9 },
  })
  // One label point per state. Only drawn without the basemap, which labels states itself.
  map.addSource('aoi-labels', { type: 'geojson', data: EMPTY })
  map.addLayer({
    id: 'aoi-label',
    type: 'symbol',
    source: 'aoi-labels',
    layout: {
      'text-field': ['upcase', ['get', 'name']],
      'text-font': LABEL_FONT,
      'text-size': 11,
      'text-letter-spacing': 0.15,
    },
    paint: { 'text-color': '#a7b3c2', 'text-halo-color': '#0b0f14', 'text-halo-width': 1.5 },
  })
  map.addLayer({
    id: 'poe-circle',
    type: 'circle',
    source: 'poe',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 3, 10, 7],
      'circle-color': '#f43f5e',
      'circle-stroke-color': '#0b0f14',
      'circle-stroke-width': 1.5,
    },
  })
  // Invisible, larger hit target so small port markers are easy to click.
  map.addLayer({
    id: 'poe-hit',
    type: 'circle',
    source: 'poe',
    paint: { 'circle-radius': 10, 'circle-opacity': 0 },
  })
  map.addLayer({
    id: 'poe-label',
    type: 'symbol',
    source: 'poe',
    minzoom: 7,
    layout: {
      'text-field': ['get', 'name'],
      'text-font': LABEL_FONT,
      'text-size': 11,
      'text-offset': [0, 1.1],
      'text-anchor': 'top',
    },
    paint: { 'text-color': '#fecdd3', 'text-halo-color': '#0b0f14', 'text-halo-width': 1.5 },
  })

  const popup = new maplibregl.Popup({ closeButton: false, className: 'osint-popup' })
  map.on('click', 'poe-hit', (e) => {
    const f = e.features?.[0]
    if (!f) return
    const p = f.properties as Pick<NodeProps, 'name' | 'code' | 'admin1_code'> & {
      sources: Citation[] | string
    }
    // MapLibre v6 keeps nested properties as objects; older versions serialized them to JSON.
    const sources =
      typeof p.sources === 'string' ? (JSON.parse(p.sources) as Citation[]) : p.sources
    const src = sources[0]?.publisher ?? ''
    const el = document.createElement('div')
    el.className = 'text-xs'
    el.innerHTML = '<strong></strong><div></div><div class="opacity-70"></div>'
    el.children[0].textContent = p.name
    el.children[1].textContent = `Port code ${p.code} · ${p.admin1_code}`
    el.children[2].textContent = `Source: ${src}`
    popup
      .setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number])
      .setDOMContent(el)
      .addTo(map)
  })
  map.on('mouseenter', 'poe-hit', () => (map.getCanvas().style.cursor = 'pointer'))
  map.on('mouseleave', 'poe-hit', () => (map.getCanvas().style.cursor = ''))
}

export default function OperationalMap({ aoi, nodes, basemap, visibility }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const [ready, setReady] = useState(false)
  const fitted = useRef(false)

  useEffect(() => {
    if (!container.current) return
    ensurePmtilesProtocol()
    const origin = window.location.origin
    const map = new maplibregl.Map({
      container: container.current,
      style: basemap ? basemapStyle(origin) : fallbackStyle(origin),
      center: [-106, 30],
      zoom: 4.2,
      attributionControl: { compact: true },
      maxBounds: [
        [-135, 12],
        [-80, 50],
      ],
    })
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), 'top-right')
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left')
    map.on('load', () => {
      addOverlays(map)
      setReady(true)
    })
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
      fitted.current = false
      setReady(false)
    }
  }, [basemap])

  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    ;(map.getSource('aoi') as GeoJSONSource).setData(toGeoJSON(aoi))
    ;(map.getSource('aoi-labels') as GeoJSONSource).setData(
      basemap || !aoi ? EMPTY : labelPoints(aoi),
    )
    ;(map.getSource('poe') as GeoJSONSource).setData(toGeoJSON(nodes, (p) => p.node_type === 'poe'))
    if (aoi && !fitted.current) {
      const b = boundsOf(aoi)
      if (b) {
        map.fitBounds(b, { padding: 40, duration: 0 })
        fitted.current = true
      }
    }
  }, [ready, aoi, nodes, basemap])

  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    const set = (ids: string[], on: boolean) =>
      ids.forEach((id) => map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none'))
    set(['aoi-fill', 'aoi-line', 'aoi-label'], visibility.aoi)
    set(['poe-circle', 'poe-hit', 'poe-label'], visibility.poe)
  }, [ready, visibility])

  return (
    <div ref={container} className="h-full w-full" aria-label="Operational map" role="region" />
  )
}
