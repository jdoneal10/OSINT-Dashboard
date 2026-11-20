import { describe, expect, it } from 'vitest'
import type { AcledWeekPoint } from '../api/types'
import { addDays, weekStart, weeklyColumns } from './acledWeekly'

describe('ACLED weeks', () => {
  it('keys a week by the Saturday that starts it', () => {
    expect(weekStart('2025-11-01')).toBe('2025-11-01') // Saturday
    expect(weekStart('2025-11-07')).toBe('2025-11-01') // Friday ends the week
    expect(weekStart('2025-11-08')).toBe('2025-11-08')
    expect(addDays('2025-11-01', 7)).toBe('2025-11-08')
  })

  it('fills empty weeks with 0 and keeps each week on one source', () => {
    const points: AcledWeekPoint[] = [
      { week: '2025-10-25', events: 2, fatalities: 1, origin: 'events' },
      { week: '2025-11-15', events: 5, fatalities: 3, origin: 'aggregate' },
    ]
    const v = weeklyColumns(points, '2025-10-25', '2025-11-07')
    expect(v.weeks).toEqual(['2025-10-25', '2025-11-01', '2025-11-08', '2025-11-15'])
    expect(v.events).toEqual([2, 0, 0, 5])
    expect(v.origins).toEqual(['events', 'events', 'aggregate', 'aggregate'])
    expect(v.firstAggregate).toBe(2)
  })

  it('returns nothing for no points', () => {
    expect(weeklyColumns([], '2025-01-04', null).weeks).toEqual([])
  })
})
