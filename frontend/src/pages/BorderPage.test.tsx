import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { routes } from '../router'
import { mockApi } from '../test/fetchMock'

vi.mock('../components/charts/Chart', () => ({
  default: ({ label }: { label: string }) => <div role="img" aria-label={label} />,
}))
vi.mock('../components/map/OperationalMap', () => ({ default: () => <div /> }))

const series = (unit: string) => ({
  metric: 'm',
  aor: ['usbp-tucson'],
  unit,
  group_by: 'demographic',
  as_of: null,
  snapshots: ['2026-10-15'],
  retrieved_at: '2026-11-11T12:00:00Z',
  notice: 'Uses U.S. Customs and Border Protection public data; not endorsed by CBP.',
  series: [{ month: '2024-01-01', group: 'Single Adults', value: 10 }],
})

function renderAt(path: string) {
  mockApi({
    '/health': {
      status: 'ok',
      version: '0',
      db: 'ok',
      postgis_version: '3.5',
      worker_last_heartbeat: null,
    },
    '/reference/adjacency': [
      {
        sector: 'usbp-tucson',
        name: 'Tucson Sector',
        adjacent_admin1: ['MX-SON'],
        field_office: 'ofo-tucson',
        method: 'Analyst-derived. Test.',
        sources: [],
      },
    ],
    '/reference/aoi': {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          id: 'mx-sonora',
          geometry: null,
          properties: { admin1_code: 'MX-SON', name: 'Sonora' },
        },
      ],
    },
    '/border/metrics': series('persons'),
    '/seizures': { aor: ['usbp-tucson'], weight: series('lbs'), events: series('events') },
    '/events/timeseries': [
      { month: '2024-01-01', admin1_code: 'MX-SON', events: 3, fatalities: 1 },
    ],
    '/events/meta': {
      total: 3,
      min_date: '2024-01-01',
      max_date: '2024-01-31',
      accessed: '2026-11-11T12:00:00Z',
      sources: ['acled'],
    },
  })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('BorderPage', () => {
  it('renders charts with caveats and attribution', async () => {
    renderAt('/border')
    expect(await screen.findByRole('img', { name: 'USBP encounters by month' })).toBeInTheDocument()
    expect(
      await screen.findByRole('img', { name: /ACLED events and fatalities/ }),
    ).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Tucson Sector' })).toBeInTheDocument()

    const caveats = screen.getByLabelText('Analytic caveats')
    expect(caveats).toHaveTextContent(/not total flow/)
    expect(caveats).toHaveTextContent(/revised until fiscal-year close/)
    expect(caveats).toHaveTextContent(/analyst-derived/)

    const footer = screen.getByLabelText('Sources and attribution')
    expect(within(footer).getByText(/not endorsed by CBP/)).toBeInTheDocument()
    expect(footer).toHaveTextContent(/ACLED \(Armed Conflict Location & Event Data\)/)
    expect(footer).toHaveTextContent(/accessed 2026-11-11/)
    expect(footer).toHaveTextContent(/Sonora/)
  })

  it('keeps both classification banners and the nav on every route', async () => {
    renderAt('/border')
    expect(screen.getByTestId('classification-top')).toBeInTheDocument()
    expect(screen.getByTestId('classification-bottom')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Border panel' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.getByRole('link', { name: 'Operational map' })).toBeInTheDocument()
  })
})
