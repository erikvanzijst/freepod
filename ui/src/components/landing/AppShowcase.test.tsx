import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { Product } from '../../api/types'
import AppShowcase from './AppShowcase'

function product(id: number, name: string, fields: Partial<Product>): Product {
  return {
    id,
    name,
    slug: name.toLowerCase(),
    icon_url: null,
    category: 'Photos',
    replaces: null,
    visibility: 'public',
    curated: true,
    created_at: '2026-01-01T00:00:00Z',
    ...fields,
  }
}

vi.mock('../../api/endpoints', () => ({
  listProducts: () =>
    Promise.resolve([
      product(1, 'Immich', { tagline: 'Your photos, kept private.', description: 'A long **Markdown** description.' }),
      product(2, 'Lemmy', { tagline: null, description: 'Only a long description.' }),
    ]),
}))

// jsdom has no IntersectionObserver; Reveal uses one to animate cards in.
vi.stubGlobal(
  'IntersectionObserver',
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
)

function renderShowcase() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AppShowcase />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AppShowcase', () => {
  it('shows the tagline as the blurb and links each card to its app page', async () => {
    renderShowcase()

    expect(await screen.findByText('Your photos, kept private.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Immich/ })).toHaveAttribute('href', '/apps/immich')
    expect(screen.getByRole('link', { name: /Lemmy/ })).toHaveAttribute('href', '/apps/lemmy')
  })

  it('never falls back to the long description', async () => {
    renderShowcase()

    await screen.findByText('Lemmy')
    expect(screen.queryByText('Only a long description.')).toBeNull()
    expect(screen.queryByText(/A long/)).toBeNull()
  })
})
