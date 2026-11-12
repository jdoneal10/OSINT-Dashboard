import { firstDay, lastDay } from './months'

/** ACLED, events extracted from news and press releases, or both. */
export type EventSource = 'acled' | 'news' | 'both'

export interface EventFilterState {
  startMonth: string // 'YYYY-MM'
  endMonth: string
  eventTypes: string[] // empty = all
  actors: { id: number; name: string }[]
  source?: EventSource // default both
}

/** Matches no source: used when "news" is chosen but no news-derived events exist yet. */
const NO_SOURCE = '__none__'

/**
 * Query params understood by the shared /events filters. ``eventSources`` lists the source
 * slugs that have events (from /events/meta); every slug except ``acled`` is news-derived.
 */
export function eventFilterParams(
  f: EventFilterState,
  eventSources: string[] = [],
): Record<string, unknown> {
  const news = eventSources.filter((s) => s !== 'acled')
  return {
    start: firstDay(f.startMonth),
    end: lastDay(f.endMonth),
    event_type: f.eventTypes.length ? f.eventTypes : undefined,
    actor: f.actors.length ? f.actors.map((a) => a.id) : undefined,
    source:
      f.source === 'acled'
        ? ['acled']
        : f.source === 'news'
          ? news.length
            ? news
            : [NO_SOURCE]
          : undefined,
  }
}

export const includesAcled = (f: EventFilterState) => f.source !== 'news'
export const includesNews = (f: EventFilterState) => f.source !== 'acled'

/** Human-readable filter summary for ACLED attribution ("which filters did you use?"). */
export function describeFilters(f: EventFilterState, allTypes: number): string {
  const types =
    f.eventTypes.length === 0 || f.eventTypes.length === allTypes
      ? 'all event types'
      : f.eventTypes.join(', ')
  const actors = f.actors.length ? `; actors: ${f.actors.map((a) => a.name).join(', ')}` : ''
  return `all of Mexico; ${f.startMonth} to ${f.endMonth}; ${types}${actors}`
}
