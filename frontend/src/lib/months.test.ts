import { describe, expect, it } from 'vitest'
import { firstDay, lastDay, monthLabel, monthsBetween, toMonth } from './months'

describe('months', () => {
  it('spans year boundaries inclusively', () => {
    expect(monthsBetween('2019-11', '2020-02')).toEqual([
      '2019-11',
      '2019-12',
      '2020-01',
      '2020-02',
    ])
  })
  it('computes first/last day including leap years', () => {
    expect(firstDay('2024-02')).toBe('2024-02-01')
    expect(lastDay('2024-02')).toBe('2024-02-29')
    expect(lastDay('2023-02-15')).toBe('2023-02-28')
  })
  it('labels and truncates', () => {
    expect(monthLabel('2026-10-01')).toBe('Oct 2026')
    expect(toMonth('2026-10-15')).toBe('2026-10')
  })
})
