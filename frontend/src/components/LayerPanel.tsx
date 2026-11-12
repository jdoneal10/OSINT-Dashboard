import type { ReactNode } from 'react'
import type { AreaProps, NodeProps, ReferenceCollection } from '../api/types'
import type { LayerVisibility } from './map/OperationalMap'

interface Props {
  aoi?: ReferenceCollection<AreaProps>
  nodes?: ReferenceCollection<NodeProps>
  basemap: boolean | null
  visibility: LayerVisibility
  onToggle: (key: keyof LayerVisibility) => void
  /** Rendered as the first section (event filters). */
  children?: ReactNode
  /** Crime-type/month picker and legend, shown under the crime toggle when it is on. */
  crimeControls?: ReactNode
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-ink-700 border-b px-4 py-3">
      <h2 className="text-ink-500 mb-2 text-[10px] font-semibold tracking-[0.16em] uppercase">
        {title}
      </h2>
      {children}
    </section>
  )
}

function Toggle(props: {
  label: string
  swatch: string
  count?: number
  on: boolean
  onChange: () => void
}) {
  return (
    <label className="hover:bg-ink-800 -mx-2 flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm">
      <input
        type="checkbox"
        checked={props.on}
        onChange={props.onChange}
        className="accent-sky-500"
      />
      <span className="h-2.5 w-2.5 rounded-sm" style={{ background: props.swatch }} />
      <span className="flex-1">{props.label}</span>
      {props.count !== undefined && (
        <span className="text-ink-500 tabular-nums">{props.count}</span>
      )}
    </label>
  )
}

export default function LayerPanel({
  aoi,
  nodes,
  basemap,
  visibility,
  onToggle,
  children,
  crimeControls,
}: Props) {
  const states = aoi?.features ?? []
  const poes = nodes?.features.filter((f) => f.properties.node_type === 'poe') ?? []
  const sectors = nodes?.features.filter((f) => f.properties.node_type === 'usbp_sector') ?? []

  return (
    <aside className="border-ink-700 bg-ink-900 flex w-80 shrink-0 flex-col overflow-y-auto border-r">
      {children && <Section title="Events">{children}</Section>}
      <Section title="Layers · Phase 2 AOI">
        <Toggle
          label="Events"
          swatch="#f43f5e"
          on={visibility.events}
          onChange={() => onToggle('events')}
        />
        <Toggle
          label="AOI states"
          swatch="linear-gradient(90deg,#f59e0b 50%,#38bdf8 50%)"
          count={states.length}
          on={visibility.aoi}
          onChange={() => onToggle('aoi')}
        />
        <Toggle
          label="Land ports of entry"
          swatch="#f43f5e"
          count={poes.length}
          on={visibility.poe}
          onChange={() => onToggle('poe')}
        />
        <Toggle
          label="Crime incidence (SESNSP)"
          swatch="linear-gradient(90deg,#3b0764,#db2777,#fda4af)"
          on={visibility.crime}
          onChange={() => onToggle('crime')}
        />
        {visibility.crime && crimeControls}
        <div className="text-ink-500 mt-2 flex gap-3 text-xs">
          <span>
            <span className="text-amber-500">■</span> Mexico
          </span>
          <span>
            <span className="text-sky-400">■</span> United States
          </span>
        </div>
      </Section>

      <Section title={`USBP sectors · ${sectors.length}`}>
        <p className="text-ink-500 mb-2 text-xs leading-relaxed">
          Listed only. No current public boundary dataset exists, so sectors are not drawn (ADR
          0002).
        </p>
        <ul className="space-y-0.5 text-sm">
          {sectors.map((s) => (
            <li key={s.id}>
              <a
                href={s.properties.sources[0]?.url}
                target="_blank"
                rel="noreferrer noopener"
                className="text-ink-300 hover:text-ink-100 hover:underline"
              >
                {s.properties.name}
              </a>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Basemap">
        {basemap === null ? (
          <p className="text-ink-500 text-xs">Checking local extract…</p>
        ) : basemap ? (
          <p className="text-ink-300 text-xs">
            Local Protomaps extract · no external tile requests
          </p>
        ) : (
          <p className="text-xs text-amber-400">
            Local extract not found. Run <code className="font-mono">make basemap</code>.
          </p>
        )}
      </Section>

      <Section title="Sources">
        <ul className="text-ink-500 space-y-1 text-xs">
          <li>Events: ACLED (Armed Conflict Location &amp; Event Data)</li>
          <li>News-derived events: public news and press releases, extracted by Claude</li>
          <li>Crime incidence: SESNSP municipal data (Mexican government)</li>
          <li>Municipalities: INEGI Marco Geoestadístico</li>
          <li>Boundaries: Natural Earth 1:10m (public domain)</li>
          <li>Ports of entry: BTS Border Crossing Entry Data</li>
          <li>Sectors: CBP public sector pages</li>
          <li>Basemap: © OpenStreetMap contributors, Protomaps</li>
        </ul>
      </Section>
    </aside>
  )
}
