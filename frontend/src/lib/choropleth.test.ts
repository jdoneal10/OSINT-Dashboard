import { describe, expect, it } from 'vitest'
import { breakLabels, crimeWindow, joinValues, quantileBreaks } from './choropleth'

describe('choropleth', () => {
  it('builds increasing quantile breaks from nonzero values', () => {
    // Skewed like municipal homicide counts: many 1-3, a long tail.
    const skewed = [
      ...Array(50).fill(1),
      ...Array(25).fill(2),
      ...Array(15).fill(5),
      9,
      12,
      20,
      30,
      40,
      60,
      80,
      120,
      190,
      400,
    ]
    expect(quantileBreaks(skewed)).toEqual([1, 2, 5, 80]) // p90 is still 5: deduplicated
    const breaks = quantileBreaks([0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55])
    expect(breaks[0]).toBe(1)
    expect(breaks).toEqual([...breaks].sort((a, b) => a - b))
    expect(new Set(breaks).size).toBe(breaks.length)
    expect(quantileBreaks([0, 0])).toEqual([])
    expect(quantileBreaks([4, 4, 4])).toEqual([4])
  })

  it('labels classes by range', () => {
    expect(breakLabels([1, 5, 20])).toEqual(['1–4', '5–19', '20+'])
    expect(breakLabels([1, 2, 3])).toEqual(['1', '2', '3+'])
  })

  it('keeps the period inside one SESNSP methodology', () => {
    const meta = [
      {
        methodology: '2015-2025',
        snapshot_date: 's',
        first_month: '2015-01-01',
        last_month: '2025-12-01',
        crime_types: [],
      },
      {
        methodology: '2026',
        snapshot_date: 's',
        first_month: '2026-01-01',
        last_month: '2026-09-01',
        crime_types: [],
      },
    ]
    expect(crimeWindow('2026-09', 3, meta)).toEqual({
      start: '2026-07',
      end: '2026-09',
      clamped: false,
    })
    expect(crimeWindow('2026-09', 12, meta)).toEqual({
      start: '2026-01',
      end: '2026-09',
      clamped: true,
    })
    expect(crimeWindow('2025-06', 12, meta).start).toBe('2024-07')
  })

  it('joins values onto municipalities by cvegeo, zero when unreported', () => {
    const square = {
      type: 'Polygon' as const,
      coordinates: [
        [
          [0, 0],
          [1, 0],
          [1, 1],
          [0, 0],
        ],
      ],
    }
    const fc = joinValues(
      {
        type: 'FeatureCollection',
        features: [
          {
            type: 'Feature',
            id: '25006',
            geometry: square,
            properties: { code: '25006', name: 'Culiacán', admin1_code: 'MX-SIN' },
          },
          {
            type: 'Feature',
            id: '25012',
            geometry: square,
            properties: { code: '25012', name: 'Mazatlán', admin1_code: 'MX-SIN' },
          },
        ],
      },
      {
        methodology: '2026',
        snapshot_date: '2026-09-30',
        crime_type: 'Homicidio',
        start: '2026-09-01',
        end: '2026-09-01',
        items: [{ admin2_code: '25006', admin1_code: 'MX-SIN', name: 'Culiacán', value: 42 }],
      },
    )
    expect(fc.features.map((f) => f.properties?.v)).toEqual([42, 0])
  })
})
