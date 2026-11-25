import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import type { EventDetail, PersonDetail, UxsSummary } from '../api/types'
import { routes } from '../router'
import { mockApi } from '../test/fetchMock'

vi.mock('../components/charts/Chart', () => ({
  default: ({ label }: { label: string }) => <div role="img" aria-label={label} />,
}))
vi.mock('../components/map/OperationalMap', () => ({ default: () => <div /> }))

const uxs: UxsSummary = {
  total: 3,
  sources: 2,
  acled_events: 1,
  months: [
    { month: '2026-10', counts: { employment: 1 } },
    { month: '2026-11', counts: { employment: 1, recovery_or_seizure: 1 } },
  ],
  breakdown: {
    activity: { employment: 2, recovery_or_seizure: 1 },
    platform: { suas_multirotor: 2, fpv: 1 },
    mission: { attack: 1, surveillance: 1 },
    payload: { explosive_or_grenade: 1 },
  },
  states: { Michoacán: 2, Sinaloa: 1 },
  caveat: 'Counts of reported events, not of underlying activity.',
  ladder: [
    {
      rung: 1,
      label: 'Observation or thermal reconnaissance',
      captured: true,
      use: 1,
      capability: 0,
      first_seen: '2026-11-02',
      last_seen: '2026-11-02',
    },
    {
      rung: 3,
      label: 'FPV and low-level flight',
      captured: true,
      use: 0,
      capability: 0,
      first_seen: null,
      last_seen: null,
    },
    {
      rung: 4,
      label: 'Payload drops',
      captured: true,
      use: 0,
      capability: 1,
      first_seen: '2026-11-09',
      last_seen: '2026-11-09',
    },
    {
      rung: 5,
      label: 'One-way attacks',
      captured: true,
      use: 1,
      capability: 0,
      first_seen: '2026-10-03',
      last_seen: '2026-10-03',
    },
    {
      rung: 6,
      label: 'Coordinated multi-drone operations',
      captured: false,
      use: 0,
      capability: 0,
      first_seen: null,
      last_seen: null,
    },
  ],
  ladder_note: 'Rungs derive from the owner framework (owner judgment).',
}

const attack: EventDetail = {
  id: 21,
  source: 'quadratin',
  source_key: 'doc9:e0',
  source_url: null,
  retrieved_at: '2026-11-10T13:00:00Z',
  confidence: 0.6,
  event_date: '2026-10-03',
  event_type: 'Explosions/Remote violence',
  sub_event_type: 'Drone strike',
  fatalities: 0,
  lon: -102.0,
  lat: 19.1,
  geo_precision: 2,
  time_precision: 1,
  admin1_code: 'MX-MIC',
  admin1_name: 'Michoacán',
  admin2_name: 'Apatzingán',
  location_name: null,
  description: 'A drone dropped explosives on a synthetic town.',
  credibility: 4,
  cluster_id: null,
  in_aoi: true,
  border_threat: null,
  uxs_activity: 'employment',
  uxs_platform: 'fpv',
  uxs_missions: ['attack'],
  uxs_payloads: ['explosive_or_grenade'],
  evidence: 'un dron lanzó explosivos',
  actors: [],
  document_ids: [9],
}

const person: PersonDetail = {
  id: 5,
  display_name: 'Ramón Sintético Pérez',
  roles: ['leader'],
  organizations: ['Cartel de Jalisco Nueva Generacion'],
  n_sources: 1,
  n_documents: 1,
  n_records: 1,
  records: [
    {
      id: 5,
      display_name: 'Ramón Sintético Pérez',
      sources: ['Quadratín Michoacán'],
      us_person: false,
      merge_id: null,
      into_id: null,
    },
  ],
  distinct_from: [],
  last_reported_on: '2026-11-10',
  us_person: false,
  disputed: false,
  dispute_note: null,
  claims: [
    {
      kind: 'role',
      value: 'leader',
      record_id: 5,
      reported_name: 'Ramón Sintético Pérez',
      actor_id: null,
      event_id: null,
      event_date: null,
      citation: {
        source: 'Quadratín Michoacán',
        source_url: 'https://example.org/a',
        document_id: 9,
        designation_id: null,
        reported_on: '2026-11-10',
        grade: 'B3',
        evidence: 'el líder sintético',
        basis: 'as reported',
      },
    },
    {
      kind: 'organization',
      record_id: 5,
      reported_name: 'Ramón Sintético Pérez',
      value: 'leader: Cartel de Jalisco Nueva Generacion',
      actor_id: 2,
      event_id: null,
      event_date: null,
      citation: {
        source: 'Quadratín Michoacán',
        source_url: null,
        document_id: 9,
        designation_id: null,
        reported_on: '2026-11-10',
        grade: 'B3',
        evidence: null,
        basis: 'as reported',
      },
    },
  ],
}

function renderAt(path: string, extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    '/health': { status: 'ok', version: '0', db: 'ok', postgis_version: '3.5', worker_last_heartbeat: null },
    '/llm/usage': { month: '2026-11-01', spent_usd: 1, cap_usd: 75, pause_threshold_usd: 60, paused: false, calls: 1, failed_calls: 0, quarantined: 0, by_stage: [] },
    '/reference/aoi': { type: 'FeatureCollection', features: [] },
    '/events/geojson': { type: 'FeatureCollection', features: [], truncated: false },
    '/events': { items: [attack], next_cursor: null },
    '/priority/uxs': uxs,
    '/priority/energy-theft': { ...uxs, total: 0, sources: 0, acled_events: 0, months: [], breakdown: {}, states: {} },
    '/persons': { items: [{ ...person, claims: undefined }], total: 1 },
    '/persons/5': person,
    ...extra,
  }) // prettier-ignore
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { fetchMock, router }
}

describe('Priority topics', () => {
  it('shows totals, the escalation ladder with uncaptured rungs, and recent events', async () => {
    const { fetchMock } = renderAt('/priority/uxs')
    expect(await screen.findByRole('heading', { name: 'Unmanned systems' })).toBeInTheDocument()
    expect(await screen.findByText('Independent sources')).toBeInTheDocument()
    expect(screen.getByText('One-way attacks')).toBeInTheDocument()
    expect(screen.getByText('not captured yet')).toBeInTheDocument()
    expect(screen.getByText(/owner framework/)).toBeInTheDocument()
    expect(
      await screen.findByText('A drone dropped explosives on a synthetic town.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'doc 9' })).toHaveAttribute('href', '/news/9')
    const urls = fetchMock.mock.calls.map(([u]) => String(u))
    expect(urls.some((u) => u.includes('/events?') && u.includes('topic=uxs'))).toBe(true)
    expect(urls.some((u) => u.includes('/events/geojson') && u.includes('topic=uxs'))).toBe(true)
    expect(screen.getByText(/1 of these events come from ACLED/)).toBeInTheDocument()
  })

  it('switches to electricity theft and shows the empty state', async () => {
    renderAt('/priority/electricity')
    expect(await screen.findByRole('heading', { name: 'Electricity theft' })).toBeInTheDocument()
    expect(
      await screen.findByText(/No electricity theft events in this period/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Sites are never inferred/)).toBeInTheDocument()
    expect(screen.queryByText(/come from ACLED/)).not.toBeInTheDocument()
  })
})

describe('People', () => {
  it('lists records with U.S. persons hidden unless the owner includes them', async () => {
    const { fetchMock } = renderAt('/persons')
    expect(await screen.findByRole('link', { name: 'Ramón Sintético Pérez' })).toHaveAttribute(
      'href',
      '/persons/5',
    )
    const first = fetchMock.mock.calls.map(([u]) => String(u)).find((u) => u.includes('/persons'))
    expect(first).not.toContain('include_us_persons')
    fireEvent.click(screen.getByLabelText('Include U.S. persons'))
    expect(await screen.findByText(/hidden by default/)).toBeInTheDocument()
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u]) => String(u).includes('include_us_persons=true')),
      ).toBe(true),
    )
  })

  it('shows every claim as reported with its source, date and grade', async () => {
    renderAt('/persons/5')
    expect(
      await screen.findByRole('heading', { name: /Ramón Sintético Pérez/ }),
    ).toBeInTheDocument()
    expect(screen.getByText(/as reported/)).toBeInTheDocument()
    const claims = screen.getByRole('table')
    expect(
      within(claims).getByText('Cartel de Jalisco Nueva Generacion (Leader)'),
    ).toBeInTheDocument()
    expect(within(claims).getAllByRole('link', { name: 'Quadratín Michoacán' })[0]).toHaveAttribute(
      'href',
      '/news/9',
    )
    expect(within(claims).getAllByLabelText(/Admiralty B3/)).toHaveLength(2)
  })

  it('lets the owner dispute and delete a record after confirming', async () => {
    const { fetchMock, router } = renderAt('/persons/5')
    fireEvent.change(await screen.findByLabelText('Dispute note'), {
      target: { value: 'wrong man' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Mark disputed' }))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
      expect(put?.[0]).toContain('/persons/5/dispute')
      expect(JSON.parse(String(put?.[1]?.body))).toEqual({ disputed: true, note: 'wrong man' })
    })
    fireEvent.click(screen.getByRole('button', { name: 'Delete record…' }))
    expect(screen.getByText(/cannot be undone/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/persons'))
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(true)
  })
})

describe('Person labeling', () => {
  it('records a safeguard violation as a person label for this document', async () => {
    const doc = {
      id: 9,
      title: 'Nota sintética',
      summary_en: 'Synthetic summary.',
      source: { slug: 'quadratin', name: 'Quadratín Michoacán', reliability: 'B' },
      url: null,
      published_at: '2026-11-10T12:00:00Z',
      retrieved_at: '2026-11-10T13:00:00Z',
      language: 'es',
      status: 'extracted',
      relevance_score: 0.9,
      duplicate_of_id: null,
      n_events: 1,
      n_seizures: 0,
      in_aoi: true,
      border_threats: [],
      clusters: [],
      admiralty: null,
      original_text: 'Texto sintético.',
      feed_summary: null,
      text_policy: 'full',
      relevance_model: null,
      llm_model: 'claude-haiku-5-5',
      prompt_version: 'extract-v9',
      llm_input_tokens: 1,
      llm_output_tokens: 1,
      events: [attack],
      seizures: [],
      persons: [
        {
          id: 6,
          display_name: 'Testigo Sintético Ruiz',
          us_person: false,
          disputed: false,
          claims: [{ kind: 'role', value: 'associate', event_id: null }],
        },
      ],
      quarantine: [],
      labels: [],
      duplicates: [],
    }
    const { fetchMock } = renderAt('/labeling/9', {
      '/labels/queue': { size: 1, done: 0, items: [] },
      '/documents/9': doc,
      '/labels': { id: 1 },
    })
    expect(await screen.findByText('Testigo Sintético Ruiz')).toBeInTheDocument()
    expect(screen.getAllByText('UxS').length).toBeGreaterThan(0) // priority chip on the event
    fireEvent.click(screen.getByLabelText(/Should not be recorded/))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([u, init]) => String(u).includes('/labels') && init?.method === 'PUT',
      )
      expect(JSON.parse(String(put?.[1]?.body))).toMatchObject({
        document_id: 9,
        target_table: 'persons',
        target_id: 6,
        verdict: 'incorrect',
        field: 'excluded_category',
      })
    })
  })
})

describe('Merge review', () => {
  const candidate = (id: number, name: string, selected: boolean, source: string) => ({
    person: { ...person, id, display_name: name, claims: undefined },
    sources: [source],
    aliases: ['El Grillo'],
    evidence: null,
    selected,
    reasons: ['names agree', 'same alias'],
    warning: null,
  })
  const suggestions = {
    hidden_us_persons: 1,
    items: [
      {
        primary_id: 7,
        us_person: false,
        candidates: [
          candidate(7, 'Darío Sintético Vega', true, 'Outlet A'),
          candidate(8, 'Darío "N"', true, 'Agency B'),
          candidate(9, 'Darío "N"', false, 'Agency C'),
        ],
      },
    ],
  }
  const posts = (mock: ReturnType<typeof renderAt>['fetchMock'], path: string) =>
    mock.mock.calls.filter(([u, init]) => init?.method === 'POST' && String(u).includes(path))

  it('merges only the ticked records, and only on a click', async () => {
    const { fetchMock } = renderAt('/persons/review', {
      '/persons/merge-suggestions': suggestions,
      '/persons/merges': { ...person, id: 7 },
    })
    expect(await screen.findByText(/suggestion\(s\) involving a U.S. person/)).toBeInTheDocument()
    expect(screen.getByLabelText('Same person: record 9')).not.toBeChecked()
    expect(posts(fetchMock, '/persons/merges')).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: /Merge 2 records/ }))
    await waitFor(() => {
      const [call] = posts(fetchMock, '/persons/merges')
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ person_ids: [7, 8], primary_id: 7 })
    })
  })

  it('records a not-the-same decision', async () => {
    const { fetchMock } = renderAt('/persons/review', {
      '/persons/merge-suggestions': suggestions,
      '/persons/distinctions': {},
    })
    fireEvent.click(await screen.findByLabelText('Record 9 is not the same person'))
    await waitFor(() => {
      const [call] = posts(fetchMock, '/persons/distinctions')
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ person_id: 7, other_ids: [9] })
    })
  })

  it('shows each published name and undoes a merge', async () => {
    const member = {
      id: 6,
      display_name: 'Ramón "N"',
      sources: ['Agency B'],
      us_person: false,
      merge_id: 31,
      into_id: 5,
    }
    const { fetchMock } = renderAt('/persons/5', {
      '/persons/5': { ...person, n_records: 2, records: [...person.records, member] },
      '/persons/merges': {},
    })
    expect(await screen.findByText('Ramón "N"')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Named as' })).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Undo merge of record 6'))
    await waitFor(() => expect(posts(fetchMock, '/persons/merges/31/undo')).toHaveLength(1))
  })
})

describe('Grid labeling (ADR 0014)', () => {
  const item = {
    event_id: 41,
    source: 'acled',
    source_key: 'SYN1',
    event_date: '2026-11-02',
    event_type: 'Riots',
    sub_event_type: null,
    admin1_name: 'Guerrero',
    admin2_name: null,
    description: 'SYNTHETIC. Armed men burned a substation.',
    actors: ['Unidentified Armed Group (Mexico)'],
    kind: 'deliberate_outage_or_sabotage',
    indicators: ['outage_in_contested_area'],
    evidence: 'burned a substation',
    prompt_version: 'grid-v3',
    document_ids: [],
    stratum: 'deliberate_outage_or_sabotage',
    label: null,
    stale: false,
  }
  const review = {
    size: 1,
    labeled: 0,
    strata: { deliberate_outage_or_sabotage: 1 },
    items: [item],
  }

  it('shows the verdict and saves a partly wrong label naming the kind', async () => {
    const { fetchMock } = renderAt('/labeling/grid', { '/grid/review': review, '/grid/labels': {} })
    expect(await screen.findByText('ACLED SYN1')).toBeInTheDocument()
    expect(screen.getByText('Kind: Deliberate outage or sabotage')).toBeInTheDocument()
    expect(screen.getByText('Indicator: Outage in contested area')).toBeInTheDocument()
    expect(screen.getByText('“burned a substation”')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Partly wrong' }))
    fireEvent.click(screen.getByLabelText('Kind: Deliberate outage or sabotage'))
    fireEvent.click(screen.getByRole('button', { name: 'Save partial' }))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
      expect(String(put?.[0])).toContain('/grid/labels')
      expect(JSON.parse(String(put?.[1]?.body))).toEqual({
        event_id: 41,
        verdict: 'partial',
        wrong: ['kind'],
        note: null,
      })
    })
  })

  it('flags a label made before the event was reclassified', async () => {
    const label = {
      id: 3,
      event_id: 41,
      verdict: 'correct',
      wrong: [],
      judged_kind: 'theft',
      judged_indicators: [],
      prompt_version: 'grid-v2',
      note: null,
      updated_at: '2026-11-23T00:00:00Z',
    }
    renderAt('/labeling/grid', {
      '/grid/review': { ...review, labeled: 1, items: [{ ...item, label, stale: true }] },
    })
    expect(
      await screen.findByText('Reclassified since it was labeled; label again.'),
    ).toBeInTheDocument()
  })

  it('drops items the event no longer has when a stale partial label is redone', async () => {
    const label = {
      id: 3,
      event_id: 41,
      verdict: 'partial',
      wrong: ['high_load_site'],
      judged_kind: 'deliberate_outage_or_sabotage',
      judged_indicators: ['high_load_site'],
      prompt_version: 'grid-v2',
      note: null,
      updated_at: '2026-11-23T00:00:00Z',
    }
    const { fetchMock } = renderAt('/labeling/grid', {
      '/grid/review': { ...review, items: [{ ...item, label, stale: true }] },
      '/grid/labels': {},
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Partly wrong' }))
    fireEvent.click(screen.getByLabelText('Kind: Deliberate outage or sabotage'))
    fireEvent.click(screen.getByRole('button', { name: 'Save partial' }))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
      expect(JSON.parse(String(put?.[1]?.body)).wrong).toEqual(['kind'])
    })
  })
})

describe('UxS labeling (ADR 0009 amendment 1)', () => {
  const item = {
    event_id: 51,
    source: 'acled',
    source_key: 'SYN9',
    event_date: '2026-11-02',
    event_type: 'Explosions/Remote violence',
    sub_event_type: 'Air/drone strike',
    admin1_name: 'Michoacán',
    admin2_name: null,
    description: 'SYNTHETIC. Members of a criminal group used drones to launch explosives.',
    actors: ['Unidentified Armed Group (Mexico)'],
    activity: 'employment',
    platform: 'unknown',
    missions: ['attack'],
    payloads: ['explosive_or_grenade'],
    capabilities: ['coordinated_multi_uxs'],
    evidence: 'used drones to launch explosives',
    prompt_version: 'uxs-v3',
    document_ids: [],
    stratum: 'employment',
    label: null,
    stale: false,
  }
  const review = { size: 1, labeled: 0, strata: { employment: 1 }, items: [item] }

  it('shows the UxS fields and saves a partly wrong label naming a payload', async () => {
    const { fetchMock } = renderAt('/labeling/uxs', { '/uxs/review': review, '/uxs/labels': {} })
    expect(await screen.findByText('ACLED SYN9')).toBeInTheDocument()
    for (const chip of [
      'Activity: Use',
      'Platform: Unknown',
      'Mission: Attack',
      'Payload: Explosive or grenade',
      'Capability: Coordinated multi-UxS operation',
    ])
      expect(screen.getByText(chip)).toBeInTheDocument()
    expect(screen.getByText(/0 of 1 events labeled · Use 1/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Partly wrong' }))
    fireEvent.click(screen.getByLabelText('Payload: Explosive or grenade'))
    fireEvent.click(screen.getByRole('button', { name: 'Save partial' }))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
      expect(String(put?.[0])).toContain('/uxs/labels')
      expect(JSON.parse(String(put?.[1]?.body))).toEqual({
        event_id: 51,
        verdict: 'partial',
        wrong: ['explosive_or_grenade'],
        note: null,
      })
    })
  })

  it('saves a wrong verdict and links to the other labeling pages', async () => {
    const { fetchMock } = renderAt('/labeling/uxs', { '/uxs/review': review, '/uxs/labels': {} })
    expect(await screen.findByRole('link', { name: 'Grid labeling →' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Record labeling →' })).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Wrong' }))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
      expect(JSON.parse(String(put?.[1]?.body))).toMatchObject({ verdict: 'incorrect', wrong: [] })
    })
  })
})
