import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { TemplateTabNew } from './TemplateTabNew'
import type { Product, ProductTemplate } from '../api/types'

vi.mock('../api/endpoints', () => ({
  getMySubdomain: vi.fn().mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' }),
  getCnameTarget: vi.fn().mockResolvedValue(''),
  checkHostname: vi.fn().mockResolvedValue({ fqdn: '', usable: true, reason: null }),
}))

vi.mock('@monaco-editor/react', () => ({
  default: ({ value, onChange, options }: { value: string; onChange?: (v: string) => void; options?: { readOnly?: boolean } }) => (
    <textarea
      data-testid="monaco-editor"
      data-readonly={options?.readOnly ? 'true' : 'false'}
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}))

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const product: Product = {
  id: 1,
  name: 'TestApp',
  description: 'Test',
  template_id: 10,
  icon_url: null,
  visibility: 'public',
  curated: false,
  created_at: '2026-01-01T00:00:00Z',
}

const existingTemplate: ProductTemplate = {
  id: 10,
  product_id: 1,
  chart_ref: 'oci://registry/test',
  chart_version: '1.0.0',
  system_values_json: { key: 'value' },
  values_schema_json: {
    type: 'object',
    properties: { name: { type: 'string', title: 'Name' } },
  },
  created_at: '2026-01-01T00:00:00Z',
  product,
}

describe('TemplateTabNew', () => {
  it('pre-populates chart ref from newest template', async () => {
    renderWithQuery(
      <TemplateTabNew
        product={product}
        templates={[existingTemplate]}
        onSave={vi.fn()}
      />,
    )

    await screen.findAllByTestId('monaco-editor')

    expect(screen.getByLabelText('Helm chart reference')).toHaveValue('oci://registry/test')
  })

  it('leaves chart version empty for new template', async () => {
    renderWithQuery(
      <TemplateTabNew
        product={product}
        templates={[existingTemplate]}
        onSave={vi.fn()}
      />,
    )

    await screen.findAllByTestId('monaco-editor')

    expect(screen.getByLabelText('Helm chart version')).toHaveValue('')
  })

  it('disables Add template button when chart version is empty', async () => {
    renderWithQuery(
      <TemplateTabNew
        product={product}
        templates={[existingTemplate]}
        onSave={vi.fn()}
      />,
    )

    await screen.findAllByTestId('monaco-editor')

    expect(screen.getByRole('button', { name: 'Add template' })).toBeDisabled()
  })

  it('enables Add template button when chart ref and version are filled', async () => {
    renderWithQuery(
      <TemplateTabNew
        product={product}
        templates={[existingTemplate]}
        onSave={vi.fn()}
      />,
    )

    fireEvent.change(screen.getByLabelText('Helm chart version'), {
      target: { value: '2.0.0' },
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Add template' })).toBeEnabled()
    })
  })

  it('disables Add template button when schema JSON is invalid', async () => {
    renderWithQuery(
      <TemplateTabNew
        product={product}
        templates={[existingTemplate]}
        onSave={vi.fn()}
      />,
    )

    fireEvent.change(screen.getByLabelText('Helm chart version'), {
      target: { value: '2.0.0' },
    })

    // Make schema invalid (await the lazily-loaded editor first)
    const editors = await screen.findAllByTestId('monaco-editor')
    const schemaEditor = editors[0]
    fireEvent.change(schemaEditor, { target: { value: '{ invalid json' } })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Add template' })).toBeDisabled()
    })
  })

  it('calls onSave with parsed values when Add template is clicked', async () => {
    const onSave = vi.fn()

    renderWithQuery(
      <TemplateTabNew
        product={product}
        templates={[existingTemplate]}
        onSave={onSave}
      />,
    )

    fireEvent.change(screen.getByLabelText('Helm chart version'), {
      target: { value: '2.0.0' },
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Add template' })).toBeEnabled()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Add template' }))

    expect(onSave).toHaveBeenCalledWith({
      chart_ref: 'oci://registry/test',
      chart_version: '2.0.0',
      values_schema_json: existingTemplate.values_schema_json,
      system_values_json: existingTemplate.system_values_json,
    })
  })

  it('shows default schema when no templates exist', async () => {
    renderWithQuery(
      <TemplateTabNew
        product={{ ...product, template_id: null }}
        templates={[]}
        onSave={vi.fn()}
      />,
    )

    const editors = await screen.findAllByTestId('monaco-editor')
    expect((editors[0] as HTMLTextAreaElement).value).toContain('$schema')
    expect(screen.getByLabelText('Helm chart reference')).toHaveValue('')
  })

  it('shows green check when schema is valid', async () => {
    renderWithQuery(
      <TemplateTabNew
        product={product}
        templates={[existingTemplate]}
        onSave={vi.fn()}
      />,
    )

    await screen.findAllByTestId('monaco-editor')

    // CheckCircleIcon renders as an SVG with a testid or we can find by the label context
    const schemaLabel = screen.getByText('User values schema')
    const indicator = schemaLabel.parentElement?.querySelector('svg')
    expect(indicator).toBeInTheDocument()
  })
})
