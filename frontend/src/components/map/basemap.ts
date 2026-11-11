import { layers, namedFlavor } from '@protomaps/basemaps'
import type { StyleSpecification } from 'maplibre-gl'

/**
 * Local-only basemap: PMTiles, glyphs and sprites are all served from /basemap by the
 * dev server (scripts/basemap.sh populates data/basemap). No third-party tile calls.
 */
export const BASEMAP_PMTILES = '/basemap/aoi.pmtiles'

const glyphs = (origin: string) => `${origin}/basemap/fonts/{fontstack}/{range}.pbf`

export function basemapStyle(origin: string): StyleSpecification {
  return {
    version: 8,
    glyphs: glyphs(origin),
    sprite: `${origin}/basemap/sprites/v4/dark`,
    sources: {
      protomaps: {
        type: 'vector',
        url: `pmtiles://${origin}${BASEMAP_PMTILES}`,
        attribution:
          '© <a href="https://openstreetmap.org/copyright">OpenStreetMap</a> · <a href="https://protomaps.com">Protomaps</a>',
      },
    },
    layers: layers('protomaps', namedFlavor('dark'), { lang: 'en' }),
  }
}

/** Plain background used when the local extract is missing (e.g. CI, fresh clone). */
export function fallbackStyle(origin: string): StyleSpecification {
  return {
    version: 8,
    glyphs: glyphs(origin),
    sources: {},
    layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#0b0f14' } }],
  }
}

export async function basemapAvailable(): Promise<boolean> {
  try {
    const res = await fetch(BASEMAP_PMTILES, { method: 'HEAD' })
    return res.ok
  } catch {
    return false
  }
}
