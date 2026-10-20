/**
 * The admin UI's read-only mode for catalog-managed products.
 *
 * The service layer is what actually refuses these writes, identically for REST
 * and the CLI; these tests cover the affordances, so an operator is told where
 * to make the change instead of discovering a 400 by clicking.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { SelectedProduct } from './SelectedProduct'
import { TemplateTabs } from './TemplateTabs'
import { updateProduct } from '../api/endpoints'
import type { Product, ProductTemplate } from '../api/types'

vi.mock('../api/endpoints', () => ({
  createTemplate: vi.fn(),
  updateProduct: vi.fn().mockResolvedValue({}),
  deleteProduct: vi.fn(),
  getProductListing: vi.fn().mockResolvedValue({ product_id: 1, license: 'AGPL-3.0', features: [], links: [], screenshots: [] }),
  updateProductTemplate: vi.fn(),
  getMyHandle: vi.fn().mockResolvedValue({ handle: 'erik', suffix: '-erik.freepod.app', domain: 'freepod.app' }),
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

const baseProduct: Product = {
  id: 1,
  name: 'Immich',
  tagline: 'Kept private.',
  description: 'Photos',
  template_id: 20,
  icon_url: null,
  category: 'Photos & video',
  replaces: 'Google Photos',
  visibility: 'public',
  slug: null,
  curated: false,
  created_at: '2026-01-01T00:00:00Z',
}

const curatedProduct: Product = { ...baseProduct, slug: 'immich', curated: true }

const makeTemplate = (id: number, product: Product): ProductTemplate => ({
  id,
  product_id: 1,
  chart_ref: 'oci://registry/immich',
  chart_version: '1.0.0',
  system_values_json: null,
  values_schema_json: null,
  created_at: '2026-01-02T00:00:00Z',
  product,
})

describe('SelectedProduct for a curated product', () => {
  it('names the catalog file and drops the click-to-edit affordances', () => {
    renderWithQuery(<SelectedProduct product={curatedProduct} onError={vi.fn()} />)

    expect(screen.getByText('products/catalog/immich/immich.yaml')).toBeInTheDocument()
    // The header and marketing fields render as plain text, not edit targets.
    for (const text of ['Immich', 'Kept private.', 'Photos', 'Photos & video', 'Google Photos']) {
      expect(screen.getByText(text)).not.toHaveAttribute('role', 'button')
    }
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled()
  })

  it('shows the license as read-only text', async () => {
    renderWithQuery(<SelectedProduct product={curatedProduct} onError={vi.fn()} />)

    expect(await screen.findByText('AGPL-3.0')).not.toHaveAttribute('role', 'button')
  })

  it('leaves the visibility control enabled', () => {
    renderWithQuery(<SelectedProduct product={curatedProduct} onError={vi.fn()} />)

    expect(screen.getByRole('combobox', { name: /visibility/i })).not.toHaveAttribute(
      'aria-disabled',
    )
  })

  it('keeps a non-curated product editable and deletable', () => {
    renderWithQuery(<SelectedProduct product={baseProduct} onError={vi.fn()} />)

    expect(screen.queryByText(/Managed by the catalog/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeEnabled()
  })
})

describe('TemplateTabs for a curated product', () => {
  it('hides the New tab', async () => {
    renderWithQuery(
      <TemplateTabs
        product={curatedProduct}
        templates={[makeTemplate(20, curatedProduct)]}
        onError={vi.fn()}
      />,
    )
    await screen.findAllByTestId('monaco-editor')

    const labels = screen.getAllByRole('tab').map((tab) => tab.textContent)
    expect(labels).toEqual(['#20'])
  })

  it('replaces Make canonical with a catalog-set indication', async () => {
    renderWithQuery(
      <TemplateTabs
        product={curatedProduct}
        templates={[makeTemplate(20, curatedProduct)]}
        onError={vi.fn()}
      />,
    )
    await screen.findAllByTestId('monaco-editor')

    expect(screen.queryByRole('button', { name: /canonical/i })).not.toBeInTheDocument()
    expect(screen.getByText('Canonical — set by the catalog.')).toBeInTheDocument()
  })

  it('still offers the New tab for a non-curated product', async () => {
    renderWithQuery(
      <TemplateTabs
        product={baseProduct}
        templates={[makeTemplate(20, baseProduct)]}
        onError={vi.fn()}
      />,
    )
    await screen.findAllByTestId('monaco-editor')

    const labels = screen.getAllByRole('tab').map((tab) => tab.textContent)
    expect(labels).toContain('New')
  })
})

describe('SelectedProduct for a database-authored product', () => {
  it('saves an edited tagline', async () => {
    renderWithQuery(<SelectedProduct product={baseProduct} onError={vi.fn()} />)

    fireEvent.click(screen.getByText('Kept private.'))
    const input = screen.getByDisplayValue('Kept private.')
    fireEvent.change(input, { target: { value: 'Yours alone.' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(updateProduct).toHaveBeenCalledWith(1, { tagline: 'Yours alone.' }))
  })

  it('saves an edited license', async () => {
    renderWithQuery(<SelectedProduct product={baseProduct} onError={vi.fn()} />)

    fireEvent.click(await screen.findByText('AGPL-3.0'))
    const input = screen.getByDisplayValue('AGPL-3.0')
    fireEvent.change(input, { target: { value: 'MIT' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(updateProduct).toHaveBeenCalledWith(1, { license: 'MIT' }))
  })
})
