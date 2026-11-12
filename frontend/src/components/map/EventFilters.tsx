import { useState } from 'react'
import { useActorSearch } from '../../api/hooks'
import type { EventTypeCount } from '../../api/types'
import type { EventFilterState } from '../../lib/eventFilters'
import { useDebounced } from '../../hooks/useDebounced'
import { eventColor } from './eventColors'
import MonthRangeSlider from './MonthRangeSlider'
import type { EventMode } from './OperationalMap'

interface Props {
  bounds: [string, string]
  types: EventTypeCount[]
  value: EventFilterState
  onChange: (next: EventFilterState) => void
  mode: EventMode
  onModeChange: (mode: EventMode) => void
  shown: number | null
  truncated: boolean
}

export default function EventFilters(props: Props) {
  const { bounds, types, value, onChange, mode, onModeChange } = props
  const [query, setQuery] = useState('')
  const debounced = useDebounced(query, 200)
  const results = useActorSearch(debounced)
  const selected = new Set(value.actors.map((a) => a.id))

  const toggleType = (t: string) => {
    const all = value.eventTypes.length === 0 ? types.map((x) => x.event_type) : value.eventTypes
    const next = all.includes(t) ? all.filter((x) => x !== t) : [...all, t]
    onChange({ ...value, eventTypes: next.length === types.length ? [] : next })
  }
  const isOn = (t: string) => value.eventTypes.length === 0 || value.eventTypes.includes(t)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-ink-300 text-xs tabular-nums">
          {props.shown === null ? 'Loading events…' : `${props.shown.toLocaleString()} events`}
          {props.truncated && <span className="text-amber-400"> (truncated)</span>}
        </span>
        <div role="radiogroup" aria-label="Event display" className="bg-ink-800 flex rounded p-0.5">
          {(['heat', 'points'] as const).map((m) => (
            <button
              key={m}
              role="radio"
              aria-checked={mode === m}
              onClick={() => onModeChange(m)}
              className={`rounded px-2 py-0.5 text-xs capitalize ${
                mode === m ? 'bg-ink-700 text-ink-100' : 'text-ink-500 hover:text-ink-300'
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      <MonthRangeSlider
        min={bounds[0]}
        max={bounds[1]}
        value={[value.startMonth, value.endMonth]}
        onChange={([s, e]) => onChange({ ...value, startMonth: s, endMonth: e })}
      />

      <fieldset>
        <legend className="text-ink-500 mb-1 text-[10px] font-semibold tracking-[0.16em] uppercase">
          Event types
        </legend>
        {types.map((t) => (
          <label
            key={t.event_type}
            className="hover:bg-ink-800 -mx-2 flex cursor-pointer items-center gap-2 rounded px-2 py-0.5 text-sm"
          >
            <input
              type="checkbox"
              checked={isOn(t.event_type)}
              onChange={() => toggleType(t.event_type)}
              className="accent-sky-500"
            />
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ background: eventColor(t.event_type) }}
            />
            <span className="flex-1 truncate">{t.event_type}</span>
            <span className="text-ink-500 tabular-nums">{t.events.toLocaleString()}</span>
          </label>
        ))}
      </fieldset>

      <div>
        <label
          htmlFor="actor-search"
          className="text-ink-500 mb-1 block text-[10px] font-semibold tracking-[0.16em] uppercase"
        >
          Actors
        </label>
        {value.actors.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1">
            {value.actors.map((a) => (
              <button
                key={a.id}
                onClick={() =>
                  onChange({ ...value, actors: value.actors.filter((x) => x.id !== a.id) })
                }
                className="bg-ink-700 text-ink-100 hover:bg-ink-500 rounded px-2 py-0.5 text-xs"
                aria-label={`Remove actor filter ${a.name}`}
              >
                {a.name} ×
              </button>
            ))}
          </div>
        )}
        <input
          id="actor-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search cartels, groups…"
          className="border-ink-700 bg-ink-950 text-ink-100 placeholder:text-ink-500 w-full rounded border px-2 py-1 text-sm focus:border-sky-500 focus:outline-none"
        />
        {debounced.trim().length >= 2 && results.data && (
          <ul className="border-ink-700 mt-1 max-h-48 overflow-y-auto rounded border">
            {results.data.length === 0 && (
              <li className="text-ink-500 px-2 py-1 text-xs">No actors with events match.</li>
            )}
            {results.data
              .filter((a) => !selected.has(a.id))
              .map((a) => (
                <li key={a.id}>
                  <button
                    onClick={() => {
                      onChange({ ...value, actors: [...value.actors, { id: a.id, name: a.name }] })
                      setQuery('')
                    }}
                    className="hover:bg-ink-800 flex w-full items-center justify-between px-2 py-1 text-left text-sm"
                  >
                    <span className="truncate">{a.name}</span>
                    <span className="text-ink-500 ml-2 shrink-0 text-xs tabular-nums">
                      {a.event_count}
                    </span>
                  </button>
                </li>
              ))}
          </ul>
        )}
      </div>
    </div>
  )
}
