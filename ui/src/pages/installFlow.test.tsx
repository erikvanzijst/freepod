import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createPortal } from 'react-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import type { Product } from '../api/types'
import Dashboard from './Dashboard'
import AppPage from './AppPage'

const auth = vi.hoisted(() => ({ user: null as null | { id: number; email: string }, setEmail: vi.fn() }))
const subdomain = vi.hoisted(() => ({ value: 'alex' as string | null }))

vi.mock('../state/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../components/subdomain/useMySubdomain', () => ({
  useMySubdomain: () => ({ data: { subdomain: subdomain.value, domain: 'example.test' }, isSuccess: true }),
}))
vi.mock('../api/endpoints', () => ({
  listProducts: () => Promise.resolve(products),
  listDeployments: () => Promise.resolve([]),
  deleteDeployment: vi.fn(),
  listPlans: () => Promise.resolve([]),
  getProductListing: () => Promise.resolve({ product_id: 2, features: [], links: [], screenshots: [] }),
}))
// The dialogs have their own tests; here they only report how they were opened.
// Portaled like the real ones, so they stay reachable above the catalog panel.
vi.mock('../components/DeployDialog', () => ({
  DeployDialog: (props: { product: Product; initialPlanId?: number; onClose: () => void; onLaunched?: () => void }) =>
    createPortal(
      <div role="dialog" aria-label="deploy">
        deploy {props.product.name} plan {props.initialPlanId ?? 'none'}
        <button onClick={props.onClose}>Cancel</button>
        <button onClick={props.onLaunched ?? props.onClose}>Launch</button>
      </div>,
      document.body,
    ),
}))
// Like the real one, a claim reports the held name and then closes the dialog.
vi.mock('../components/subdomain/ClaimSubdomainDialog', () => ({
  ClaimSubdomainDialog: (props: { open: boolean; onClose: () => void; onClaimed?: (name: string) => void }) =>
    props.open ? createPortal(
      <div role="dialog" aria-label="claim">
        <button
          onClick={() => {
            subdomain.value = 'alex'
            props.onClaimed?.('alex')
            props.onClose()
          }}
        >
          Claim
        </button>
        <button onClick={props.onClose}>Not now</button>
      </div>,
      document.body,
    ) : null,
}))
vi.mock('../components/apppage/useAppListing', () => ({
  useAppListing: () => ({
    loading: false,
    listing: {
      id: 2,
      slug: 'immich',
      name: 'Immich',
      tagline: '',
      description: '',
      category: '',
      replaces: [],
      iconUrl: null,
      version: '',
      updatedAt: '',
      license: '',
      screenshots: [],
      features: [],
      releases: [],
      links: [],
      plans: [
        { id: 5, name: 'Free', priceCents: 0, description: '' },
        { id: 6, name: 'Pro', priceCents: 900, description: '' },
      ],
    },
  }),
}))

const products: Product[] = [
  {
    id: 2,
    name: 'Immich',
    slug: 'immich',
    template_id: 10,
    visibility: 'public',
    curated: true,
    created_at: '2026-01-01T00:00:00Z',
  },
]

function Location() {
  const location = useLocation()
  return <output aria-label="location">{location.pathname + location.search}</output>
}

async function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/apps/:slug" element={<AppPage />} />
        </Routes>
        <Location />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  auth.user = { id: 1, email: 'alex@example.com' }
  auth.setEmail.mockReset()
  subdomain.value = 'alex'
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
})

async function installImmich() {
  await renderAt('/apps/immich')
  fireEvent.click(screen.getAllByRole('button', { name: /Install Immich/ })[0])
}

describe('Install on an app page', () => {
  it('opens the deploy dialog over the page with the chosen plan', async () => {
    await installImmich()

    expect(await screen.findByRole('dialog', { name: 'deploy' })).toHaveTextContent('deploy Immich plan 6')
    expect(screen.getByRole('heading', { level: 1, name: 'Immich' })).toBeInTheDocument()
    expect(screen.getByLabelText('location')).toHaveTextContent('/apps/immich?install=1&plan=6')
  })

  it('stays on the page when the dialog is closed', async () => {
    await installImmich()
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByLabelText('location')).toHaveTextContent(/^\/apps\/immich$/)
  })

  it('moves to the dashboard once the app launches', async () => {
    await installImmich()
    fireEvent.click(await screen.findByRole('button', { name: 'Launch' }))

    expect(screen.getByLabelText('location')).toHaveTextContent(/^\/$/)
  })

  it('asks for a subdomain first, then continues to the deploy dialog', async () => {
    subdomain.value = null
    await installImmich()

    fireEvent.click(await screen.findByRole('button', { name: 'Claim' }))

    expect(await screen.findByRole('dialog', { name: 'deploy' })).toHaveTextContent('deploy Immich plan 6')
  })

  it('ends the install when the claim is declined', async () => {
    subdomain.value = null
    await installImmich()

    fireEvent.click(await screen.findByRole('button', { name: 'Not now' }))

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByLabelText('location')).toHaveTextContent(/^\/apps\/immich$/)
  })

  it('returns an anonymous visitor to the install after sign-up', async () => {
    auth.user = null
    auth.setEmail.mockImplementation((email: string) => {
      auth.user = { id: 1, email }
    })
    await installImmich()

    fireEvent.change(await screen.findByLabelText('Work email'), { target: { value: 'new@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    expect(auth.setEmail).toHaveBeenCalledWith('new@example.com')
    expect(screen.getByLabelText('location')).toHaveTextContent('/apps/immich?install=1&plan=6')
    expect(await screen.findByRole('dialog', { name: 'deploy' })).toHaveTextContent('deploy Immich plan 6')
  })

  it('ignores an install request for an anonymous visitor', async () => {
    auth.user = null
    await renderAt('/apps/immich?install=1&plan=6')

    await screen.findByRole('heading', { level: 1, name: 'Immich' })
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('Installing from the dashboard', () => {
  async function installFromPanel() {
    await renderAt('/')
    // A new user's starter app opens the catalog panel on that app's row.
    fireEvent.click(await screen.findByRole('button', { name: /Immich/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Install' }))
  }

  it('opens the deploy dialog over the dashboard', async () => {
    await installFromPanel()

    expect(await screen.findByRole('dialog', { name: 'deploy' })).toHaveTextContent('deploy Immich plan none')
    expect(screen.getByLabelText('location')).toHaveTextContent(/^\/\?/)
  })

  it('closes the dialog and the panel once the app launches', async () => {
    await installFromPanel()
    fireEvent.click(await screen.findByRole('button', { name: 'Launch' }))

    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'deploy' })).toBeNull())
    expect(screen.getByLabelText('location')).toHaveTextContent(/^\/$/)
  })

  it('asks for a subdomain first when the user holds none', async () => {
    subdomain.value = null
    await installFromPanel()

    expect(await screen.findByRole('dialog', { name: 'claim' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'deploy' })).toBeNull()
  })
})
