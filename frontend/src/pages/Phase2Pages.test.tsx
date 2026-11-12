import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import type { DocumentDetail, DocumentSummary, EventDetail } from '../api/types'
import { routes } from '../router'
import { mockApi } from '../test/fetchMock'

vi.mock('../components/map/OperationalMap', () => ({ default: () => <div /> }))

const summary: DocumentSummary = {
  id: 7,
  title: 'Enfrentamiento en Culiacán',
  summary_en: 'Two armed groups clashed in Culiacán.',
  source: { slug: 'zetatijuana', name: 'Zeta Tijuana', reliability: 'B' },
  url: 'https://example.org/a',
  published_at: '2026-11-10T12:00:00Z',
  retrieved_at: '2026-11-10T13:00:00Z',
  language: 'es',
  status: 'extracted',
  relevance_score: 0.9,
  duplicate_of_id: null,
  n_events: 1,
  n_seizures: 0,
  in_aoi: true,
  clusters: [
    {
      id: 3,
      reliability: 'A',
      credibility: 2,
      admiralty: 'A2',
      n_documents: 2,
      n_independent_sources: 2,
      has_conflicts: true,
      acled_corroborated: true,
    },
  ],
  admiralty: 'A2',
}

const event: EventDetail = {
  id: 11,
  source: 'zetatijuana',
  source_key: 'doc7:e0',
  source_url: null,
  retrieved_at: '2026-11-10T13:00:00Z',
  confidence: 0.6,
  event_date: '2026-11-09',
  event_type: 'Battles',
  sub_event_type: 'Armed clash',
  fatalities: 3,
  lon: -107.39,
  lat: 24.8,
  geo_precision: 2,
  time_precision: 1,
  admin1_code: 'MX-SIN',
  admin1_name: 'Sinaloa',
  admin2_name: 'Culiacán',
  location_name: null,
  description: 'Two armed groups clashed.',
  credibility: 2,
  cluster_id: 3,
  in_aoi: true,
  evidence: 'se enfrentaron dos grupos armados',
  actors: [{ id: 1, name: 'Sinaloa Cartel', type: 'tco', role: 'perpetrator' }],
  document_ids: [7],
}

const detail: DocumentDetail = {
  ...summary,
  original_text: 'Texto original del artículo.',
  feed_summary: null,
  text_policy: 'full',
  relevance_model: 'qwen3:4b/filter-v1',
  llm_model: 'claude-haiku-5-5',
  prompt_version: 'extract-v3',
  llm_input_tokens: 1200,
  llm_output_tokens: 300,
  events: [event],
  seizures: [],
  quarantine: [],
  labels: [],
  duplicates: [],
}

function renderAt(path: string, extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    '/health': {
      status: 'ok',
      version: '0',
      db: 'ok',
      postgis_version: '3.5',
      worker_last_heartbeat: null,
    },
    '/llm/usage': {
      month: '2026-11-01',
      spent_usd: 61,
      cap_usd: 75,
      pause_threshold_usd: 60,
      paused: true,
      calls: 10,
      failed_calls: 1,
      quarantined: 0,
      by_stage: [],
    },
    '/reference/aoi': { type: 'FeatureCollection', features: [] },
    '/events/types': [{ event_type: 'Battles', events: 1 }],
    '/documents/sources': [
      { slug: 'zetatijuana', name: 'Zeta Tijuana', reliability: 'B', documents: 1 },
    ],
    '/documents': { items: [summary], next_cursor: null },
    '/documents/7': detail,
    ...extra,
  })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return fetchMock
}

describe('News feed', () => {
  it('shows Admiralty grade, corroboration and conflicts, and keeps filters in the URL', async () => {
    const fetchMock = renderAt('/news?source=zetatijuana')
    const feed = await screen.findByRole('region', { name: 'News feed' })
    expect(await within(feed).findByText('Enfrentamiento en Culiacán')).toBeInTheDocument()
    expect(
      within(feed).getByLabelText(/Admiralty A2: Completely reliable source; probably true/),
    ).toBeInTheDocument()
    expect(within(feed).getByText('conflicting reports')).toBeInTheDocument()
    expect(within(feed).getByText('ACLED-corroborated')).toBeInTheDocument()
    expect(within(feed).getByText(/Corroboration includes data from ACLED/)).toBeInTheDocument()
    expect(
      within(feed).getByRole('link', { name: /Cluster 3: 2 independent sources/ }),
    ).toHaveAttribute('href', '/clusters/3')
    expect(screen.getByRole('checkbox', { name: /Zeta Tijuana/ })).toBeChecked()
    const urls = fetchMock.mock.calls.map(([u]) => String(u))
    expect(
      urls.some((u) => u.startsWith('/api/documents?') && u.includes('source=zetatijuana')),
    ).toBe(true)
  })
})

describe('Document detail', () => {
  it('shows original text, English summary, extracted records with evidence and provenance', async () => {
    renderAt('/news/7')
    expect(await screen.findByText('Texto original del artículo.')).toBeInTheDocument()
    expect(screen.getByText('Two armed groups clashed in Culiacán.')).toBeInTheDocument()
    expect(screen.getByText(/se enfrentaron dos grupos armados/)).toBeInTheDocument()
    expect(screen.getByText('Sinaloa Cartel')).toBeInTheDocument()
    expect(screen.getByText(/claude-haiku-5-5 · extract-v3 · 1200 in/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Label this document' })).toHaveAttribute(
      'href',
      '/labeling/7',
    )
  })
})

describe('Budget indicator', () => {
  it('shows spend against the cap and the paused state', async () => {
    renderAt('/news')
    const budget = await screen.findByRole('status', { name: 'LLM budget' })
    await waitFor(() => expect(budget).toHaveTextContent('$61.00 / $75'))
    expect(budget).toHaveTextContent('API paused')
  })
})

describe('Labeling', () => {
  it('saves a record verdict and the relevance decision through PUT /labels', async () => {
    const fetchMock = renderAt('/labeling/7', {
      '/labels/queue': {
        size: 1,
        done: 0,
        items: [
          {
            document_id: 7,
            source: 'zetatijuana',
            status: 'extracted',
            title: 'Enfrentamiento en Culiacán',
            n_records: 1,
            n_labeled_records: 0,
            relevance_labeled: false,
            done: false,
          },
        ],
      },
      '/labels': { id: 1 },
    })
    const bench = await screen.findByRole('region', { name: 'Labeling workbench' })
    fireEvent.click(await within(bench).findByRole('button', { name: 'Yes' }))
    fireEvent.click(within(bench).getByRole('button', { name: 'Correct' }))
    await waitFor(() => {
      const puts = fetchMock.mock.calls.filter(
        ([, init]) => (init as RequestInit | undefined)?.method === 'PUT',
      )
      expect(puts).toHaveLength(2)
    })
    const bodies = fetchMock.mock.calls
      .filter(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')
      .map(([, init]) => JSON.parse(String((init as RequestInit).body)))
    expect(bodies).toContainEqual({
      document_id: 7,
      target_table: 'documents',
      target_id: 7,
      field: 'relevant',
      verdict: 'correct',
    })
    expect(bodies).toContainEqual({
      document_id: 7,
      target_table: 'events',
      target_id: 11,
      verdict: 'correct',
      field: '',
      note: null,
    })
  })

  it('pre-ticks and saves the outside-AOI scope flag for records outside the AOI', async () => {
    const outside = { ...detail, events: [{ ...event, in_aoi: false }] }
    const fetchMock = renderAt('/labeling/7', {
      '/labels/queue': { size: 0, done: 0, items: [] },
      '/documents/7': outside,
      '/labels': { id: 2 },
    })
    const bench = await screen.findByRole('region', { name: 'Labeling workbench' })
    expect(await within(bench).findByRole('checkbox', { name: /Outside AOI/ })).toBeChecked()
    fireEvent.click(within(bench).getByRole('button', { name: 'Correct' }))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
      expect(JSON.parse(String(put?.[1]?.body))).toMatchObject({
        target_table: 'events',
        verdict: 'correct',
        field: 'out_of_aoi',
      })
    })
  })

  it('requires naming the wrong fields before saving a partial verdict', async () => {
    renderAt('/labeling/7', { '/labels/queue': { size: 0, done: 0, items: [] } })
    const bench = await screen.findByRole('region', { name: 'Labeling workbench' })
    fireEvent.click(await within(bench).findByRole('button', { name: 'Partly wrong' }))
    const save = within(bench).getByRole('button', { name: 'Save partial' })
    expect(save).toBeDisabled()
    fireEvent.click(within(bench).getByRole('checkbox', { name: 'person_named' }))
    expect(save).toBeEnabled()
  })
})

describe('Designations', () => {
  it('hides individual listings by default and explains the rule when shown', async () => {
    const fetchMock = renderAt('/designations', {
      '/designations': {
        total: 1,
        items: [
          {
            id: 1,
            source: 'ofac',
            source_url: 'https://example.org/sdn',
            retrieved_at: '2026-11-10T00:00:00Z',
            designation_type: 'sdn',
            program: 'SDGT;SDNTK',
            action: 'listed',
            action_date: '2026-11-09',
            title: 'SDN listing',
            listed_parties: [{ name: 'EXAMPLE TRADING S.A.', type: 'entity' }],
            actors: [],
          },
        ],
      },
    })
    expect(await screen.findByText('EXAMPLE TRADING S.A.')).toBeInTheDocument()
    expect(screen.getByTitle(/carries no listing date/)).toHaveTextContent('≤ 2026-11-09')
    const first = fetchMock.mock.calls
      .map(([u]) => String(u))
      .find((u) => u.startsWith('/api/designations'))
    expect(first).not.toContain('include_individual_listings')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include individual listings' }))
    expect(screen.getByText(/does not profile or track people/)).toBeInTheDocument()
  })
})
