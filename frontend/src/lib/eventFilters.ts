import { firstDay, lastDay } from './months'

export interface EventFilterState {
  startMonth: string // 'YYYY-MM'
  endMonth: string
  eventTypes: string[] // empty = all
  actors: { id: number; name: string }[]
}

/** Query params understood by the shared /events filters. */
export function eventFilterParams(f: EventFilterState): Record<string, unknown> {
  return {
    start: firstDay(f.startMonth),
    end: lastDay(f.endMonth),
    event_type: f.eventTypes.length ? f.eventTypes : undefined,
    actor: f.actors.length ? f.actors.map((a) => a.id) : undefined,
  }
}

/** Human-readable filter summary for ACLED attribution ("which filters did you use?"). */
export function describeFilters(f: EventFilterState, allTypes: number): string {
  const types =
    f.eventTypes.length === 0 || f.eventTypes.length === allTypes
      ? 'all event types'
      : f.eventTypes.join(', ')
  const actors = f.actors.length ? `; actors: ${f.actors.map((a) => a.name).join(', ')}` : ''
  return `six Mexican border states; ${f.startMonth} to ${f.endMonth}; ${types}${actors}`
}
