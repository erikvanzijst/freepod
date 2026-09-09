import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { TemplateTabs } from './TemplateTabs'
import type { Product, ProductTemplate } from '../api/types'

vi.mock('../api/endpoints', () => ({
  createTemplate: vi.fn(),
  updateProductTemplate: vi.fn(),
  getMySubdomain: vi.fn().mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' }),
  getCnameTarget: vi.fn().mockResolvedValue(''),
  checkHostname: vi.fn().mockResolvedValue({ fqdn: '', usable: true, reason: null }),
}))

vi.mock('@monaco-editor/react', () => ({
  default: () => <div data-testid="monaco-editor" />,
}))

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const product: Product = {
  id: 1,
  name: 'TestApp',
  description: 'Test',
  template_id: 20,
  icon_url: null,
  visibility: 'public',
  curated: false,
  created_at: '2026-01-01T00:00:00Z',
}

const makeTemplate = (id: number, createdAt: string): ProductTemplate => ({
  id,
  product_id: 1,
  chart_ref: 'oci://registry/test',
  chart_version: '1.0.0',
  system_values_json: null,
  values_schema_json: null,
  created_at: createdAt,
  product,
})

const templates: ProductTemplate[] = [
  makeTemplate(10, '2026-01-01T00:00:00Z'),
  makeTemplate(20, '2026-01-02T00:00:00Z'),
  makeTemplate(30, '2026-01-03T00:00:00Z'),
]

describe('TemplateTabs', () => {
  it('renders a tab for each template sorted chronologically', async () => {
    renderWithQuery(
      <TemplateTabs product={product} templates={templates} onError={vi.fn()} />,
    )

    // Let the lazily-loaded editors in the active tab resolve first.
    await screen.findAllByTestId('monaco-editor')

    const tabs = screen.getAllByRole('tab')
    // 3 template tabs + 1 "New" tab
    expect(tabs).toHaveLength(4)
    expect(tabs[0]).toHaveTextContent('#10')
    expect(tabs[1]).toHaveTextContent('#20')
    expect(tabs[2]).toHaveTextContent('#30')
    expect(tabs[3]).toHaveTextContent('New')
  })

  it('defaults to the canonical template tab', async () => {
    renderWithQuery(
      <TemplateTabs product={product} templates={templates} onError={vi.fn()} />,
    )

    await screen.findAllByTestId('monaco-editor')

    // template_id is 20, so #20 tab should be selected
    const tab20 = screen.getByRole('tab', { name: /#20/ })
    expect(tab20).toHaveAttribute('aria-selected', 'true')
  })

  it('defaults to New tab when no templates exist', async () => {
    renderWithQuery(
      <TemplateTabs
        product={{ ...product, template_id: null }}
        templates={[]}
        onError={vi.fn()}
      />,
    )

    await screen.findAllByTestId('monaco-editor')

    const newTab = screen.getByRole('tab', { name: /New/ })
    expect(newTab).toHaveAttribute('aria-selected', 'true')
  })

  it('shows canonical star indicator on the canonical template tab', async () => {
    renderWithQuery(
      <TemplateTabs product={product} templates={templates} onError={vi.fn()} />,
    )

    await screen.findAllByTestId('monaco-editor')

    // The canonical tab (#20) should have a star icon (rendered as an SVG)
    const tab20 = screen.getByRole('tab', { name: /#20/ })
    const svg = tab20.querySelector('svg')
    expect(svg).toBeInTheDocument()

    // Non-canonical tabs should not have an SVG icon
    const tab10 = screen.getByRole('tab', { name: '#10' })
    const svg10 = tab10.querySelector('svg')
    expect(svg10).not.toBeInTheDocument()
  })

  it('falls back to newest template when no canonical is set', async () => {
    const productNoCanonical = { ...product, template_id: null }

    renderWithQuery(
      <TemplateTabs
        product={productNoCanonical}
        templates={templates}
        onError={vi.fn()}
      />,
    )

    await screen.findAllByTestId('monaco-editor')

    // Should default to newest template (#30)
    const tab30 = screen.getByRole('tab', { name: /#30/ })
    expect(tab30).toHaveAttribute('aria-selected', 'true')
  })
})
