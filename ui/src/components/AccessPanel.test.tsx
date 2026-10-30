import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import type { Deployment } from '../api/types'
import { AccessPanel } from './AccessPanel'

const getMock = vi.fn()
vi.mock('../api/endpoints', () => ({ getDeploymentAccess: (...args: unknown[]) => getMock(...args) }))

function renderPanel(auth: Deployment['auth']) {
  const deployment = { id: 'd1', user_id: 7, auth } as Deployment
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AccessPanel deployment={deployment} />
    </QueryClientProvider>,
  )
}

describe('AccessPanel', () => {
  it('shows a listed deployment entries and no controls', async () => {
    getMock.mockResolvedValue({
      enabled: true, protocol: 'header', access: 'listed', owner_email: 'o@example.com', limit: 500,
      entries: [
        { id: 'a', email: 'ana@example.com', name: 'Ana', created_at: '2026-10-01T10:00:00Z', bound_at: '2026-10-22T10:00:00Z' },
        { id: 'j', email: 'jules@example.org', name: null, created_at: '2026-10-27T10:00:00Z', bound_at: null },
      ],
    })
    renderPanel({ enabled: true, protocol: 'header', access: 'listed', listed_count: 2 })
    expect(await screen.findByText('ana@example.com')).toBeInTheDocument()
    expect(screen.getByText('jules@example.org')).toBeInTheDocument()
    expect(screen.getByText('not signed in yet')).toBeInTheDocument()
    expect(screen.getByText(/signed in 2026-10-22/)).toBeInTheDocument()
    expect(screen.getByText('Access (only listed people)')).toBeInTheDocument()
    expect(getMock).toHaveBeenCalledWith(7, 'd1')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('states the mode of an open deployment without reading a list', () => {
    getMock.mockReset()
    renderPanel({ enabled: true, protocol: 'oidc', access: 'anyone', listed_count: null })
    expect(screen.getByText('Access (any Freepod account)')).toBeInTheDocument()
    expect(getMock).not.toHaveBeenCalled()
  })

  it('renders nothing without Sign in with Freepod', () => {
    const { container } = renderPanel(null)
    expect(container).toBeEmptyDOMElement()
  })
})
