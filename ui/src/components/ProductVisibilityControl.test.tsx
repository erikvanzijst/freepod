import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { ProductVisibilityControl } from './ProductVisibilityControl'
import type { Product } from '../api/types'

const updateProductMock = vi.fn()

vi.mock('../api/endpoints', () => ({
  updateProduct: (...args: unknown[]) => updateProductMock(...args),
}))

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const product: Product = {
  id: 7,
  name: 'TestApp',
  description: 'Test',
  template_id: 10,
  icon_url: null,
  visibility: 'admin',
  curated: false,
  created_at: '2026-01-01T00:00:00Z',
}

async function selectOption(label: string) {
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Visibility' }))
  fireEvent.click(await screen.findByRole('option', { name: label }))
}

describe('ProductVisibilityControl', () => {
  it('shows the current setting', () => {
    renderWithQuery(<ProductVisibilityControl product={product} onError={vi.fn()} />)

    expect(screen.getByRole('combobox', { name: 'Visibility' })).toHaveTextContent('Admin only')
    expect(screen.getByText('Hidden from end users; visible to administrators only.')).toBeInTheDocument()
  })

  it('describes a public product as offered to end users', () => {
    renderWithQuery(
      <ProductVisibilityControl product={{ ...product, visibility: 'public' }} onError={vi.fn()} />,
    )

    expect(screen.getByRole('combobox', { name: 'Visibility' })).toHaveTextContent('Public')
    expect(screen.getByText('Offered to end users in the product catalog.')).toBeInTheDocument()
  })

  it('describes an unlisted product as hidden from the storefront only', () => {
    renderWithQuery(
      <ProductVisibilityControl product={{ ...product, visibility: 'unlisted' }} onError={vi.fn()} />,
    )

    expect(screen.getByRole('combobox', { name: 'Visibility' })).toHaveTextContent('Unlisted')
    expect(
      screen.getByText('Available via the API and CLI, hidden from the storefront.'),
    ).toBeInTheDocument()
  })

  it('offers all three settings', async () => {
    renderWithQuery(<ProductVisibilityControl product={product} onError={vi.fn()} />)
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Visibility' }))

    const options = await screen.findAllByRole('option')
    expect(options.map((option) => option.textContent)).toEqual(['Public', 'Unlisted', 'Admin only'])
  })

  it('persists a change to unlisted', async () => {
    updateProductMock.mockResolvedValue({ ...product, visibility: 'unlisted' })

    renderWithQuery(
      <ProductVisibilityControl product={{ ...product, visibility: 'public' }} onError={vi.fn()} />,
    )
    await selectOption('Unlisted')

    await waitFor(() =>
      expect(updateProductMock).toHaveBeenCalledWith(7, { visibility: 'unlisted' }),
    )
  })

  it('persists a change to public', async () => {
    updateProductMock.mockResolvedValue({ ...product, visibility: 'public' })

    renderWithQuery(<ProductVisibilityControl product={product} onError={vi.fn()} />)
    await selectOption('Public')

    await waitFor(() =>
      expect(updateProductMock).toHaveBeenCalledWith(7, { visibility: 'public' }),
    )
  })

  it('persists a change back to admin only', async () => {
    updateProductMock.mockResolvedValue({ ...product, visibility: 'admin' })

    renderWithQuery(
      <ProductVisibilityControl product={{ ...product, visibility: 'public' }} onError={vi.fn()} />,
    )
    await selectOption('Admin only')

    await waitFor(() =>
      expect(updateProductMock).toHaveBeenCalledWith(7, { visibility: 'admin' }),
    )
  })

  it('does not call the API when the selection is unchanged', async () => {
    updateProductMock.mockClear()

    renderWithQuery(<ProductVisibilityControl product={product} onError={vi.fn()} />)
    await selectOption('Admin only')

    expect(updateProductMock).not.toHaveBeenCalled()
  })

  it('reports a failed change to the caller', async () => {
    const error = new Error('nope')
    updateProductMock.mockRejectedValue(error)
    const onError = vi.fn()

    renderWithQuery(<ProductVisibilityControl product={product} onError={onError} />)
    await selectOption('Public')

    await waitFor(() => expect(onError).toHaveBeenCalled())
    expect(onError.mock.calls[0][0]).toBe(error)
  })
})
