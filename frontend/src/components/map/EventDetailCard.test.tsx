import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { EventDetail } from '../../api/types'
import { mockApi } from '../../test/fetchMock'
import EventDetailCard from './EventDetailCard'

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
  border_threat: null,
  evidence: null,
  actors: [],
  document_ids: [7],
}

function renderCard(ev: EventDetail) {
  mockApi({ [`/events/${ev.id}`]: ev })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter([
    { path: '/', element: <EventDetailCard id={ev.id} onClose={() => {}} /> },
  ])
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('EventDetailCard precision', () => {
  it.each([
    [1, 'near location; exact day'],
    [2, 'near location; within a week'],
    // 3 is stored for a month-level date, an unknown date and a date taken from publication.
    [3, 'near location; month or less precise'],
    [null, 'near location; not recorded'],
  ])('words time precision %s', async (precision, text) => {
    renderCard({ ...event, time_precision: precision })
    expect(await screen.findByText(text)).toBeInTheDocument()
  })
})
