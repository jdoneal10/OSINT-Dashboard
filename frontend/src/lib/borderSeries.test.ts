import { describe, expect, it } from 'vitest'
import { pivot, snapshotNote, violenceTotals } from './borderSeries'

describe('pivot', () => {
  it('fills a dense month axis and orders groups by total', () => {
    const p = pivot(
      [
        { month: '2024-01-01', group: 'FMUA', value: 5 },
        { month: '2024-03-01', group: 'Single Adults', value: 50 },
        { month: '2024-03-01', group: 'FMUA', value: 1 },
      ],
      ['2024-01', '2024-03'],
    )
    expect(p.months).toEqual(['2024-01', '2024-02', '2024-03'])
    expect(p.series).toEqual([
      { name: 'Single Adults', data: [0, 0, 50] },
      { name: 'FMUA', data: [5, 0, 1] },
    ])
  })
  it('drops points outside the range and names ungrouped series Total', () => {
    const p = pivot([{ month: '2018-01-01', group: null, value: 9 }], ['2024-01', '2024-01'])
    expect(p.series).toEqual([])
    const q = pivot([{ month: '2024-01-01', group: null, value: 9 }])
    expect(q.series).toEqual([{ name: 'Total', data: [9] }])
  })
})

describe('violenceTotals', () => {
  it('sums admin1 rows per month', () => {
    const v = violenceTotals(
      [
        { month: '2024-02-01', admin1_code: 'MX-SON', events: 3, fatalities: 1 },
        { month: '2024-02-01', admin1_code: 'MX-CHH', events: 2, fatalities: 4 },
      ],
      ['2024-01', '2024-02'],
    )
    expect(v).toEqual({ months: ['2024-01', '2024-02'], events: [0, 5], fatalities: [0, 5] })
  })
})

describe('snapshotNote', () => {
  const base = {
    metric: 'x',
    aor: [],
    unit: null,
    group_by: null,
    as_of: null,
    retrieved_at: null,
    notice: '',
    series: [],
  }
  it('describes one or many snapshots', () => {
    expect(snapshotNote({ ...base, snapshots: ['2026-10-15'] })).toBe('CBP snapshot of 2026-10-15')
    expect(snapshotNote({ ...base, snapshots: ['2024-10-17', '2026-10-15'] })).toMatch(
      /2024-10-17 to 2026-10-15/,
    )
    expect(snapshotNote(undefined)).toBeNull()
  })
})
