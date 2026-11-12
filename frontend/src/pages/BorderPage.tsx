import { useMemo, useState } from 'react'
import {
  useAdjacency,
  useAoi,
  useBorderMetrics,
  useEventTimeseries,
  useEventsMeta,
  useSeizures,
} from '../api/hooks'
import type { MetricSeries } from '../api/types'
import Chart, { type ChartOption } from '../components/charts/Chart'
import { pivot, snapshotNote, violenceTotals, type Value } from '../lib/borderSeries'
import { localDate } from '../lib/dates'
import { firstDay, monthLabel, toMonth } from '../lib/months'

/** FY20 starts October 2019 (Phase 1 exit criterion: FY20 to present). */
const START = '2019-10'
const END = toMonth(new Date().toISOString())
const RANGE: [string, string] = [START, END]

type SeizureScope = 'sector' | 'field_office' | 'both'

function stackedBars(
  months: string[],
  series: { name: string; data: Value[] }[],
  unit: string,
): ChartOption {
  return {
    grid: { left: 56, right: 16, top: 36, bottom: 48 },
    legend: { top: 0, type: 'scroll' },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (v: unknown) => `${Number(v).toLocaleString()} ${unit}`,
    },
    dataZoom: [{ type: 'slider', height: 14, bottom: 8 }],
    xAxis: { type: 'category', data: months.map(monthLabel) },
    yAxis: { type: 'value', name: unit, nameTextStyle: { fontSize: 10 } },
    series: series.map((s) => ({ ...s, type: 'bar', stack: 'total', barMaxWidth: 14 })),
  }
}

function Card({
  title,
  subtitle,
  note,
  children,
}: {
  title: string
  subtitle?: string
  note?: string | null
  children: React.ReactNode
}) {
  return (
    <section className="border-ink-700 bg-ink-900 rounded-md border">
      <header className="border-ink-700 flex items-baseline justify-between gap-4 border-b px-4 py-2">
        <div>
          <h2 className="text-ink-100 text-sm font-semibold">{title}</h2>
          {subtitle && <p className="text-ink-500 text-xs">{subtitle}</p>}
        </div>
        {note && <span className="text-ink-500 shrink-0 text-[11px]">{note}</span>}
      </header>
      <div className="px-2 py-2">{children}</div>
    </section>
  )
}

function Empty({ what }: { what: string }) {
  return (
    <p className="text-ink-500 flex h-40 items-center justify-center text-xs">
      No {what} for this selection yet.
    </p>
  )
}

export default function BorderPage() {
  const adjacency = useAdjacency()
  const aoi = useAoi(1)
  const meta = useEventsMeta()
  const [sectorSlug, setSectorSlug] = useState<string | null>(null)
  const [scope, setScope] = useState<SeizureScope>('sector')

  const sectors = adjacency.data ?? []
  const sector = sectors.find((s) => s.sector === sectorSlug) ?? sectors[0]
  const stateNames = useMemo(() => {
    const names = new Map(
      (aoi.data?.features ?? []).map((f) => [f.properties.admin1_code, f.properties.name]),
    )
    return (sector?.adjacent_admin1 ?? []).map((c) => names.get(c) ?? c)
  }, [aoi.data, sector])

  const enabled = Boolean(sector)
  const encounters = useBorderMetrics(
    {
      metric: 'encounters',
      aor: sector?.sector,
      group_by: 'demographic',
      start: firstDay(START),
    },
    enabled,
  )
  const seizureAors =
    scope === 'sector'
      ? [sector?.sector]
      : scope === 'field_office'
        ? [sector?.field_office]
        : [sector?.sector, sector?.field_office]
  const seizures = useSeizures(
    { aor: seizureAors.filter(Boolean), start: firstDay(START) },
    enabled && seizureAors.every(Boolean),
  )
  const violence = useEventTimeseries(
    { admin1: sector?.adjacent_admin1, start: firstDay(START) },
    enabled,
  )

  const encounterChart = useMemo(() => {
    const p = pivot(encounters.data?.series ?? [], RANGE)
    return p.series.length ? stackedBars(p.months, p.series, 'encounters') : null
  }, [encounters.data])
  const seizureChart = useMemo(() => {
    const p = pivot(seizures.data?.weight.series ?? [], RANGE)
    return p.series.length ? stackedBars(p.months, p.series, 'lbs') : null
  }, [seizures.data])
  const violenceChart = useMemo((): ChartOption | null => {
    const v = violenceTotals(violence.data ?? [], RANGE, meta.data?.max_date)
    if (!v.events.some((x) => x !== null && x > 0)) return null
    return {
      grid: { left: 48, right: 48, top: 36, bottom: 48 },
      legend: { top: 0 },
      tooltip: { trigger: 'axis' },
      dataZoom: [{ type: 'slider', height: 14, bottom: 8 }],
      xAxis: { type: 'category', data: v.months.map(monthLabel) },
      yAxis: [
        { type: 'value', name: 'events', nameTextStyle: { fontSize: 10 } },
        { type: 'value', name: 'fatalities', nameTextStyle: { fontSize: 10 } },
      ],
      series: [
        {
          name: 'Events',
          type: 'bar',
          data: v.events,
          barMaxWidth: 14,
          itemStyle: { color: '#f59e0b' },
        },
        {
          name: 'Fatalities',
          type: 'line',
          connectNulls: false,
          yAxisIndex: 1,
          data: v.fatalities,
          symbol: 'none',
          lineStyle: { width: 1.5 },
          itemStyle: { color: '#f43f5e' },
        },
      ],
    }
  }, [violence.data, meta.data?.max_date])

  const cbp: MetricSeries | undefined = encounters.data ?? seizures.data?.weight

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-4 px-6 py-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-ink-100 text-lg font-semibold">Border panel</h1>
            <p className="text-ink-500 text-xs">
              CBP encounters and seizures by area of responsibility, next to violence in the
              adjacent Mexican states · FY20 to present
            </p>
          </div>
          <label className="text-ink-300 flex items-center gap-2 text-xs">
            USBP sector
            <select
              value={sector?.sector ?? ''}
              onChange={(e) => setSectorSlug(e.target.value)}
              className="border-ink-700 bg-ink-950 text-ink-100 rounded border px-2 py-1 text-sm"
            >
              {sectors.map((s) => (
                <option key={s.sector} value={s.sector}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <aside
          aria-label="Analytic caveats"
          className="rounded-md border border-amber-900/60 bg-amber-950/30 px-4 py-2.5 text-xs leading-relaxed text-amber-100/90"
        >
          <strong className="text-amber-200">Read with care.</strong> Raw counts reflect enforcement
          effort, reporting and media attention, not total flow; compare trends, not levels. CBP
          figures are revised until fiscal-year close. Sector ↔ state adjacency is analyst-derived
          (no public sector boundaries exist), so edge sectors may border extra states.
        </aside>

        <Card
          title="USBP encounters"
          subtitle={`${sector?.name ?? '…'} · by demographic`}
          note={snapshotNote(encounters.data)}
        >
          {encounterChart ? (
            <Chart option={encounterChart} label="USBP encounters by month" />
          ) : (
            <Empty what="encounter data" />
          )}
        </Card>

        <Card
          title="Drug seizures (lbs)"
          subtitle="by drug type · USBP between ports, OFO at ports of entry"
          note={snapshotNote(seizures.data?.weight)}
        >
          <div role="radiogroup" aria-label="Seizure scope" className="mb-1 flex gap-1 px-2">
            {(
              [
                ['sector', sector?.name ?? 'Sector'],
                ['field_office', 'Paired field office'],
                ['both', 'Both'],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                role="radio"
                aria-checked={scope === key}
                onClick={() => setScope(key)}
                className={`rounded px-2 py-0.5 text-xs ${
                  scope === key ? 'bg-ink-700 text-ink-100' : 'text-ink-500 hover:text-ink-300'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {seizureChart ? (
            <Chart option={seizureChart} label="Drug seizures by month and drug type" />
          ) : (
            <Empty what="seizure data" />
          )}
        </Card>

        <Card
          title="Violence in adjacent Mexican states"
          subtitle={`${stateNames.length ? stateNames.join(', ') : '…'}${
            meta.data?.max_date
              ? ` · ACLED events available through ${meta.data.max_date} (licence-tier lag); later months left blank`
              : ''
          }`}
          note={meta.data?.accessed ? `ACLED accessed ${localDate(meta.data.accessed)}` : null}
        >
          {violenceChart ? (
            <Chart option={violenceChart} label="ACLED events and fatalities by month" />
          ) : (
            <Empty what="ACLED events" />
          )}
        </Card>

        <footer
          aria-label="Sources and attribution"
          className="text-ink-500 space-y-1 pb-4 text-[11px] leading-relaxed"
        >
          <p>
            {cbp?.notice ??
              'Uses U.S. Customs and Border Protection public data; not endorsed by CBP.'}{' '}
            {cbp?.retrieved_at && `Retrieved ${localDate(cbp.retrieved_at)}.`}
          </p>
          <p>
            Violence events: ACLED (Armed Conflict Location &amp; Event Data),{' '}
            <a
              href="https://acleddata.com"
              target="_blank"
              rel="noreferrer noopener"
              className="underline"
            >
              acleddata.com
            </a>
            {meta.data?.accessed && `, accessed ${localDate(meta.data.accessed)}`}. Filtered to{' '}
            {stateNames.join(', ') || 'the adjacent states'}, all event types, aggregated to monthly
            counts.
          </p>
          {sector?.method && <p>Adjacency method: {sector.method}</p>}
        </footer>
      </div>
    </div>
  )
}
