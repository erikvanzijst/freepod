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
      product(1, 'Lemmy', { category: 'Forums & communities', tagline: null, description: 'Only a long description.' }),
      product(2, 'Immich', {
        tagline: 'Your photos, kept private.',
        description: 'A long **Markdown** description.',
        replaces: 'Google Photos · iCloud Photos',
      }),
      product(3, 'PhotoPrism', { tagline: 'Another photo app.', replaces: 'Google Photos' }),
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
  it('shows each need once, with what it replaces and the apps that do it, linking to the catalog', async () => {
    renderShowcase()

    const photos = (await screen.findByText('Photos')).closest('a')!
    expect(photos).toHaveAttribute('href', '/apps?category=Photos')
    expect(photos).toHaveTextContent('An alternative to Google Photos or iCloud Photos')
    expect(photos).toHaveTextContent('Your photos, kept private.')
    expect(photos).toHaveTextContent('With Immich or PhotoPrism')
  })

  it('puts the most familiar needs first', async () => {
    renderShowcase()

    await screen.findByText('Photos')
    const headings = screen.getAllByRole('link').map((a) => a.getAttribute('href'))
    expect(headings.indexOf('/apps?category=Photos')).toBeLessThan(headings.indexOf('/apps?category=Forums%20%26%20communities'))
  })

  it('never falls back to the long description', async () => {
    renderShowcase()

    await screen.findByText('Forums & communities')
    expect(screen.queryByText('Only a long description.')).toBeNull()
    expect(screen.queryByText(/A long/)).toBeNull()
  })
})
