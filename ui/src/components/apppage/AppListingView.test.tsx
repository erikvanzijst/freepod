import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { AppListingView } from './AppListingView'
import type { AppListing } from './listing'

vi.mock('../../api/endpoints', () => ({ listProducts: () => Promise.resolve([]) }))

// jsdom has no ResizeObserver; the release notes use one to decide on folding.
vi.stubGlobal(
  'ResizeObserver',
  class {
    observe() {}
    disconnect() {}
  },
)

function renderListing(listing: AppListing) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AppListingView listing={listing} onInstall={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const bare: AppListing = {
  id: 7,
  slug: 'lemmy',
  name: 'Lemmy',
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
  plans: [{ id: 1, name: 'Free', priceCents: 0, description: '' }],
}

const full: AppListing = {
  ...bare,
  slug: 'immich',
  name: 'Immich',
  tagline: 'Your photos, kept private.',
  description: 'First **paragraph**.\n\nSecond paragraph. <script>alert(1)</script>',
  category: 'Photos',
  replaces: ['Google Photos'],
  version: '3.3.1',
  updatedAt: '2026-09-01T10:00:00Z',
  license: 'AGPL-3.0',
  screenshots: [
    {
      thumbnailUrl: '/api/static/screenshots/a-thumb.webp',
      url: '/api/static/screenshots/a.webp',
      caption: 'Timeline',
      form: 'desktop',
      credit: { text: 'Immich · MIT', href: 'https://immich.app' },
    },
    { thumbnailUrl: '/api/static/screenshots/b-thumb.webp', url: '/api/static/screenshots/b.webp', caption: 'Phone', form: 'mobile' },
  ],
  features: [{ title: 'Automatic backup', body: 'Your phone uploads new photos.', icon: 'sync' }],
  releases: [{ version: '3.3.1', availableAt: '2026-09-01T10:00:00Z', notes: 'Sharing got better.' }],
  links: [{ label: 'Website', href: 'https://immich.app', kind: 'website' }],
  plans: [
    { id: 1, name: 'Free', priceCents: 0, description: '' },
    { id: 2, name: 'Starter', priceCents: 500, description: '* **50GB storage**' },
  ],
}

describe('AppListingView', () => {
  it('renders every section of a fully described app', () => {
    renderListing(full)

    expect(screen.getAllByText('Your photos, kept private.').length).toBeGreaterThan(0)
    expect(screen.getByText('paragraph').tagName).toBe('STRONG')
    expect(screen.getByText('Automatic backup')).toBeInTheDocument()
    expect(screen.getByText('Sharing got better.')).toBeInTheDocument()
    expect(screen.getAllByText('AGPL-3.0').length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: /Website/ })).toHaveAttribute('href', 'https://immich.app')
    expect(screen.getByRole('button', { name: 'Open screenshot: Timeline' })).toBeInTheDocument()
  })

  it('drops raw HTML from Markdown', () => {
    const { container } = renderListing(full)
    expect(container.querySelector('script')).toBeNull()
  })

  it('shows only thumbnails until the viewer opens', () => {
    const { container } = renderListing(full)
    const sources = [...container.querySelectorAll('img')].map((img) => img.getAttribute('src'))

    expect(sources).toContain('/api/static/screenshots/a-thumb.webp')
    expect(sources).not.toContain('/api/static/screenshots/a.webp')
    expect(sources).not.toContain('/api/static/screenshots/b.webp')
  })

  it('omits every empty section for an app with only a name and plans', () => {
    renderListing(bare)

    expect(screen.getByRole('heading', { level: 1, name: 'Lemmy' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Install/ }).length).toBeGreaterThan(0)
    expect(screen.queryByText(/About Lemmy/)).toBeNull()
    expect(screen.queryByText(/What.s new/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /Open screenshot/ })).toBeNull()
    expect(screen.queryByText('Version')).toBeNull()
    expect(screen.queryByText('Mobile apps')).toBeNull()
  })

  it('links to the docs only for apps they cover', () => {
    renderListing(full)
    for (const link of screen.getAllByRole('link', { name: /Immich docs/ })) {
      expect(link).toHaveAttribute('href', '/docs/apps/products/immich')
    }

    renderListing({ ...bare, slug: 'no-such-app', name: 'Nameless' })
    expect(screen.queryByRole('link', { name: /Nameless docs/ })).toBeNull()
  })
})
