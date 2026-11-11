import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from '../App'
import { renderWithQuery } from '../test/utils'
import { CLASSIFICATION_TEXT } from './ClassificationBanner'

// MapLibre needs WebGL, which jsdom lacks; the banner contract doesn't depend on the map.
vi.mock('./map/OperationalMap', () => ({ default: () => <div data-testid="map" /> }))

describe('classification banner', () => {
  it('uses the exact required marking', () => {
    expect(CLASSIFICATION_TEXT).toBe('UNCLASSIFIED — PUBLICLY AVAILABLE INFORMATION ONLY')
  })

  it('renders at the top and bottom of the app', () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    renderWithQuery(<App />)
    expect(screen.getByTestId('classification-top')).toHaveTextContent(CLASSIFICATION_TEXT)
    expect(screen.getByTestId('classification-bottom')).toHaveTextContent(CLASSIFICATION_TEXT)
  })
})
