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
  it('maps the source choice to source slugs', () => {
    const sources = ['acled', 'doj', 'zetatijuana']
    expect(eventFilterParams({ ...base, source: 'acled' }, sources).source).toEqual(['acled'])
    expect(eventFilterParams({ ...base, source: 'news' }, sources).source).toEqual([
      'doj',
      'zetatijuana',
    ])
    expect(eventFilterParams({ ...base, source: 'news' }, ['acled']).source).toEqual(['__none__'])
    expect(eventFilterParams({ ...base, source: 'both' }, sources).source).toBeUndefined()
  })
  it('limits to border threats when asked', () => {
    expect(eventFilterParams({ ...base, borderThreatsOnly: true }).border_threat).toEqual(['any'])
    expect(eventFilterParams(base).border_threat).toBeUndefined()
  })
  it('describes filters for ACLED attribution', () => {
    expect(describeFilters(base, 6)).toBe('all of Mexico; 2018-01 to 2024-02; all event types')
    expect(
      describeFilters({ ...base, eventTypes: ['Battles'], actors: [{ id: 1, name: 'CJNG' }] }, 6),
    ).toMatch(/Battles; actors: CJNG$/)
  })
})
