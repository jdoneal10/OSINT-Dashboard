import { describe, expect, it } from 'vitest'
import { describeFilters, eventFilterParams } from './eventFilters'
import { toQuery } from './query'

const base = { startMonth: '2018-01', endMonth: '2024-02', eventTypes: [], actors: [] }

describe('event filters', () => {
  it('maps to API params with full-month bounds', () => {
    expect(eventFilterParams(base)).toEqual({
      start: '2018-01-01',
      end: '2024-02-29',
      event_type: undefined,
      actor: undefined,
    })
  })
  it('repeats list params in the query string', () => {
    const params = eventFilterParams({
      ...base,
      eventTypes: ['Battles', 'Riots'],
      actors: [{ id: 7, name: 'X' }],
    })
    expect(toQuery(params)).toBe(
      '?start=2018-01-01&end=2024-02-29&event_type=Battles&event_type=Riots&actor=7',
    )
  })
  it('describes filters for ACLED attribution', () => {
    expect(describeFilters(base, 6)).toBe(
      'six Mexican border states; 2018-01 to 2024-02; all event types',
    )
    expect(
      describeFilters({ ...base, eventTypes: ['Battles'], actors: [{ id: 1, name: 'CJNG' }] }, 6),
    ).toMatch(/Battles; actors: CJNG$/)
  })
})
