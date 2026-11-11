import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { renderWithQuery } from '../test/utils'
import HealthIndicator from './HealthIndicator'

describe('HealthIndicator', () => {
  it('shows API offline when /health fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 503 })))
    renderWithQuery(<HealthIndicator />)
    expect(await screen.findByText('API offline')).toBeInTheDocument()
  })

  it('shows PostGIS version when healthy', async () => {
    const body = {
      status: 'ok',
      version: '0.1.0',
      db: 'ok',
      postgis_version: '3.5.3',
      worker_last_heartbeat: null,
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body))))
    renderWithQuery(<HealthIndicator />)
    expect(await screen.findByText('API ok')).toBeInTheDocument()
    expect(screen.getByText(/PostGIS 3\.5\.3/)).toBeInTheDocument()
  })
})
