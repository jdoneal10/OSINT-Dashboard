import { useEffect, useMemo, useState } from 'react'
import { Link, NavLink, useParams } from 'react-router'
import {
  useAoi,
  useEventList,
  useEventPoints,
  usePriorityEnergy,
  usePriorityUxs,
} from '../api/hooks'
import type { EventDetail, LadderRow, TopicSummary } from '../api/types'
import Chart, { type ChartOption } from '../components/charts/Chart'
import { basemapAvailable } from '../components/map/basemap'
import EventDetailCard from '../components/map/EventDetailCard'
import OperationalMap from '../components/map/OperationalMap'
import Panel from '../components/news/Panel'
import { plural } from '../lib/format'
import { categoryLabel, PERIODS, periodStart, type Topic } from '../lib/priority'

const INPUT =
  'border-ink-700 bg-ink-800 text-ink-100 rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none'

const TOPICS: Record<Topic, { path: string; title: string; blurb: string; series: string }> = {
  uxs: {
    path: 'uxs',
    title: 'Unmanned systems',
    blurb:
      'Criminal use, seizure, procurement, assembly, training and prosecution involving drones and other unmanned systems (IR 8).',
    series: 'activity',
  },
  energy_theft: {
    path: 'electricity',
    title: 'Electricity theft',
    blurb:
      'Reported cases of electricity stolen by or for criminal activity: raids, investigations, prosecutions and official statements (IR 9). Sites are never inferred.',
    series: 'method',
  },
}

const VISIBILITY = { aoi: true, poe: false, events: true, crime: false, acledStates: false }

export default function PriorityPage() {
  const { topic: slug } = useParams()
  const topic: Topic = slug === 'electricity' ? 'energy_theft' : 'uxs'
  const meta = TOPICS[topic]
  const [periodKey, setPeriodKey] = useState('1y')
  const period = PERIODS.find((p) => p.key === periodKey) ?? PERIODS[1]
  const params = useMemo(() => ({ start: periodStart(period) }), [period])

  const uxs = usePriorityUxs(params)
  const energy = usePriorityEnergy(params)
  const summary: TopicSummary | undefined = topic === 'uxs' ? uxs.data : energy.data
  const error = (topic === 'uxs' ? uxs.error : energy.error)?.message

  return (
    <div className="h-full overflow-y-auto px-6 py-4">
      <div className="mx-auto max-w-7xl space-y-4">
        <header className="flex flex-wrap items-end gap-3">
          <div className="mr-auto">
            <nav aria-label="Priority topics" className="mb-1 flex gap-1">
              {(Object.keys(TOPICS) as Topic[]).map((t) => (
                <NavLink
                  key={t}
                  to={`/priority/${TOPICS[t].path}`}
                  className={({ isActive }) =>
                    `rounded px-2 py-0.5 text-xs font-medium ${
                      isActive || (t === 'uxs' && !slug)
                        ? 'bg-sky-500/15 text-sky-300'
                        : 'text-ink-500 hover:text-ink-300'
                    }`
                  }
                >
                  {TOPICS[t].title}
                </NavLink>
              ))}
            </nav>
            <h1 className="text-ink-100 text-lg font-semibold">{meta.title}</h1>
            <p className="text-ink-500 max-w-3xl text-xs">{meta.blurb}</p>
          </div>
          <select
            aria-label="Period"
            value={periodKey}
            onChange={(e) => setPeriodKey(e.target.value)}
            className={INPUT}
          >
            {PERIODS.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </header>

        {error && <p className="text-xs text-rose-300">Data unavailable: {error}</p>}
        {summary && <Tiles summary={summary} />}
        {summary && summary.total === 0 && (
          <p className="text-ink-500 border-ink-700 rounded border border-dashed px-4 py-3 text-xs">
            No {meta.title.toLowerCase()} events in this period yet. They appear as documents are
            extracted with prompt extract-v7 or later.
          </p>
        )}

        <div className="grid gap-4 lg:grid-cols-5">
          <Panel title="Map" className="lg:col-span-3" aside="Reported locations, source precision">
            <TopicMap topic={topic} start={params.start} />
          </Panel>
          {topic === 'uxs' ? (
            <Panel title="Escalation ladder" className="lg:col-span-2" aside="Owner framework">
              <Ladder rows={uxs.data?.ladder ?? []} note={uxs.data?.ladder_note} />
            </Panel>
          ) : (
            <Panel title="What the power fed" className="lg:col-span-2" aside="As reported">
              <Bars counts={summary?.breakdown.powered} />
            </Panel>
          )}
        </div>

        <Panel title="Monthly trend" aside={summary?.caveat}>
          <Trend summary={summary} series={meta.series} />
        </Panel>

        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {(topic === 'uxs'
            ? [
                ['Platform', 'platform'],
                ['Mission', 'mission'],
                ['Payload', 'payload'],
                ['Capability (rungs 6-8)', 'capability'],
              ]
            : [
                ['Method', 'method'],
                ['Facilitator (role)', 'facilitator'],
              ]
          ).map(([title, key]) => (
            <Panel key={key} title={title}>
              <Bars counts={summary?.breakdown[key]} />
            </Panel>
          ))}
          <Panel title="States">
            <Bars counts={summary?.states} raw />
          </Panel>
        </div>

        <Panel title="Recent events" aside="Newest first; open a source document for the text">
          <RecentEvents topic={topic} start={params.start} />
        </Panel>

        {summary && summary.acled_events > 0 && (
          <p className="text-ink-500 text-[11px] leading-relaxed">
            {summary.acled_events.toLocaleString()} of these events come from ACLED (Armed Conflict
            Location &amp; Event Data),{' '}
            <a
              href="https://acleddata.com"
              target="_blank"
              rel="noreferrer noopener"
              className="underline"
            >
              acleddata.com
            </a>
            , classified from ACLED's event notes.
          </p>
        )}
      </div>
    </div>
  )
}

function Tiles({ summary }: { summary: TopicSummary }) {
  const months = summary.months
  const latest = months.at(-1)
  const tiles = [
    ['Reported events', summary.total.toLocaleString()],
    ['Independent sources', summary.sources.toLocaleString()],
    ['States', Object.keys(summary.states).length.toLocaleString()],
    ['Latest month', latest ? latest.month : '—'],
  ]
  return (
    <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {tiles.map(([label, value]) => (
        <div key={label} className="border-ink-700 bg-ink-900 rounded-md border px-4 py-3">
          <dt className="text-ink-500 text-[11px] tracking-wide uppercase">{label}</dt>
          <dd className="text-ink-100 mt-1 text-xl font-semibold tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function TopicMap({ topic, start }: { topic: Topic; start?: string }) {
  const aoi = useAoi(2)
  const [basemap, setBasemap] = useState<boolean | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const points = useEventPoints({ topic: [topic], start })
  useEffect(() => {
    let live = true
    basemapAvailable().then((ok) => live && setBasemap(ok))
    return () => {
      live = false
    }
  }, [])
  return (
    <div className="relative h-[360px] overflow-hidden rounded">
      {basemap !== null && (
        <OperationalMap
          aoi={aoi.data}
          events={points.data}
          eventMode="points"
          basemap={basemap}
          visibility={VISIBILITY}
          onEventClick={setSelected}
        />
      )}
      {selected !== null && <EventDetailCard id={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

function Ladder({ rows, note }: { rows: LadderRow[]; note?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.use + r.capability))
  return (
    <div className="space-y-2 text-xs">
      <ol className="space-y-1.5">
        {[...rows].reverse().map((r) => (
          <li key={r.rung} className="grid grid-cols-[2.5rem_1fr_auto] items-center gap-2">
            <span className="text-ink-500 font-mono tabular-nums">
              {r.rung === 1 ? '1–2' : r.rung}
            </span>
            <div>
              <div className={r.captured ? 'text-ink-100' : 'text-ink-500 italic'}>{r.label}</div>
              {r.captured ? (
                <div className="bg-ink-800 mt-0.5 flex h-1.5 overflow-hidden rounded">
                  <div className="bg-rose-400" style={{ width: `${(r.use / max) * 100}%` }} />
                  <div
                    className="bg-amber-400/70"
                    style={{ width: `${(r.capability / max) * 100}%` }}
                  />
                </div>
              ) : (
                <div className="text-ink-500 text-[11px]">not captured yet</div>
              )}
            </div>
            <span className="text-ink-300 text-right tabular-nums">
              {r.captured ? (
                <>
                  {r.use} <span className="text-ink-500">use</span> · {r.capability}{' '}
                  <span className="text-ink-500">cap.</span>
                  {r.last_seen && (
                    <div className="text-ink-500 text-[11px]">last {r.last_seen}</div>
                  )}
                </>
              ) : (
                '—'
              )}
            </span>
          </li>
        ))}
      </ol>
      <p className="text-ink-500 flex gap-3 text-[11px]">
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-sm bg-rose-400" />
          reported use
        </span>
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-sm bg-amber-400/70" />
          capability (seizure, procurement, assembly, training, prosecution)
        </span>
      </p>
      {note && <p className="text-ink-500 text-[11px] leading-relaxed">{note}</p>}
    </div>
  )
}

function Trend({ summary, series }: { summary?: TopicSummary; series: string }) {
  const option: ChartOption = useMemo(() => {
    const months = summary?.months ?? []
    const keys = Object.keys(summary?.breakdown[series] ?? {})
    return {
      grid: { left: 36, right: 12, top: 28, bottom: 24 },
      tooltip: { trigger: 'axis' },
      legend: { top: 0, data: keys.map(categoryLabel) },
      xAxis: { type: 'category', data: months.map((m) => m.month) },
      yAxis: { type: 'value', minInterval: 1 },
      series: keys.map((k) => ({
        name: categoryLabel(k),
        type: 'bar',
        stack: 'total',
        data: months.map((m) => m.counts[k] ?? 0),
      })),
    }
  }, [summary, series])
  return <Chart option={option} height={240} label="Monthly count of reported events" />
}

function Bars({ counts, raw = false }: { counts?: Record<string, number>; raw?: boolean }) {
  const entries = Object.entries(counts ?? {})
  if (!entries.length) return <p className="text-ink-500 text-xs">None reported.</p>
  const max = Math.max(...entries.map(([, n]) => n))
  return (
    <ul className="space-y-1.5 text-xs">
      {entries.map(([k, n]) => (
        <li key={k}>
          <div className="flex justify-between gap-2">
            <span className="text-ink-300 truncate">{raw ? k : categoryLabel(k)}</span>
            <span className="text-ink-100 tabular-nums">{n}</span>
          </div>
          <div className="bg-ink-800 mt-0.5 h-1 rounded">
            <div className="h-1 rounded bg-sky-400/80" style={{ width: `${(n / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  )
}

function details(e: EventDetail): string[] {
  if (e.uxs_activity) {
    return [
      categoryLabel(e.uxs_activity),
      categoryLabel(e.uxs_platform ?? 'unknown'),
      ...(e.uxs_missions ?? []).map(categoryLabel),
      ...(e.uxs_payloads ?? []).filter((p) => p !== 'none_reported').map(categoryLabel),
    ]
  }
  if (e.energy_method) {
    return [
      categoryLabel(e.energy_method),
      ...(e.energy_powered ?? []).map(categoryLabel),
      ...(e.energy_facilitator && e.energy_facilitator !== 'none_reported'
        ? [categoryLabel(e.energy_facilitator)]
        : []),
      ...(e.energy_scale ? [e.energy_scale] : []),
    ]
  }
  return []
}

function RecentEvents({ topic, start }: { topic: Topic; start?: string }) {
  const { data, isPending } = useEventList({ topic: [topic], start, limit: 25 })
  if (isPending) return <p className="text-ink-500 text-xs">Loading…</p>
  const items = data?.items ?? []
  if (!items.length) return <p className="text-ink-500 text-xs">No events in this period.</p>
  return (
    <table className="w-full text-left text-xs">
      <thead className="text-ink-500">
        <tr>
          <th className="py-1 pr-3 font-medium">Date</th>
          <th className="py-1 pr-3 font-medium">Place</th>
          <th className="py-1 pr-3 font-medium">Reported detail</th>
          <th className="py-1 pr-3 font-medium">Summary</th>
          <th className="py-1 font-medium">Source</th>
        </tr>
      </thead>
      <tbody className="divide-ink-800 divide-y">
        {items.map((e) => (
          <tr key={e.id} className="align-top">
            <td className="text-ink-300 py-1.5 pr-3 whitespace-nowrap tabular-nums">
              {e.event_date}
            </td>
            <td className="text-ink-300 py-1.5 pr-3">
              {[e.location_name, e.admin2_name, e.admin1_name].filter(Boolean).join(', ') || '—'}
            </td>
            <td className="py-1.5 pr-3">
              <div className="flex flex-wrap gap-1">
                {details(e).map((d) => (
                  <span key={d} className="bg-ink-800 text-ink-300 rounded px-1.5 py-0.5">
                    {d}
                  </span>
                ))}
              </div>
            </td>
            <td className="text-ink-300 py-1.5 pr-3">{e.description ?? '—'}</td>
            <td className="py-1.5 whitespace-nowrap">
              {e.document_ids.length ? (
                e.document_ids.map((id) => (
                  <Link key={id} to={`/news/${id}`} className="mr-2 text-sky-400 hover:underline">
                    doc {id}
                  </Link>
                ))
              ) : (
                <span className="text-ink-500">{e.source}</span>
              )}
              <div className="text-ink-500">{plural(e.actors.length, 'actor')}</div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
