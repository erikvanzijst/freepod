import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { DeployDialogContent } from './DeployDialogContent'
import type { Product } from '../api/types'

vi.mock('../api/endpoints', () => ({
  getMySubdomain: vi.fn().mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' }),
  getCnameTarget: vi.fn().mockResolvedValue(''),
  checkHostname: vi.fn().mockResolvedValue({ fqdn: '', usable: true, reason: null }),
}))

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const product: Product = {
  id: 1,
  name: 'TestApp',
  description: 'A test application',
  template_id: 10,
  icon_url: null,
  visibility: 'public',
  curated: false,
  created_at: '2026-01-01T00:00:00Z',
}

const schema = {
  type: 'object',
  properties: {
    host: { type: 'string', title: 'hostname' },
  },
  required: ['host'],
}

describe('DeployDialogContent', () => {
  it('renders product name and description', () => {
    renderWithQuery(
      <DeployDialogContent
        product={product}
        valuesSchemaJson={null}
        initialValuesJson={null}
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByText('TestApp')).toBeInTheDocument()
    expect(screen.getByText('A test application')).toBeInTheDocument()
  })

  it('renders form fields from schema', () => {
    renderWithQuery(
      <DeployDialogContent
        product={product}
        valuesSchemaJson={schema}
        initialValuesJson={null}
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByText('Configure application values:')).toBeInTheDocument()
  })

  it('does not render Launch button when onLaunch is not provided', () => {
    renderWithQuery(
      <DeployDialogContent
        product={product}
        valuesSchemaJson={null}
        initialValuesJson={null}
        onChange={vi.fn()}
      />,
    )

    expect(screen.queryByRole('button', { name: 'Launch' })).not.toBeInTheDocument()
  })

  it('does not render Cancel button when onCancel is not provided', () => {
    renderWithQuery(
      <DeployDialogContent
        product={product}
        valuesSchemaJson={null}
        initialValuesJson={null}
        onChange={vi.fn()}
      />,
    )

    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
  })

  it('renders Launch and Cancel buttons when handlers are provided', () => {
    renderWithQuery(
      <DeployDialogContent
        product={product}
        valuesSchemaJson={null}
        initialValuesJson={null}
        onChange={vi.fn()}
        onLaunch={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: 'Launch' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
  })

  it('disables Launch button when launchDisabled is true', () => {
    renderWithQuery(
      <DeployDialogContent
        product={product}
        valuesSchemaJson={null}
        initialValuesJson={null}
        onChange={vi.fn()}
        onLaunch={vi.fn()}
        launchDisabled
      />,
    )

    expect(screen.getByRole('button', { name: 'Launch' })).toBeDisabled()
  })

  it('shows Launching text when launchPending is true', () => {
    renderWithQuery(
      <DeployDialogContent
        product={product}
        valuesSchemaJson={null}
        initialValuesJson={null}
        onChange={vi.fn()}
        onLaunch={vi.fn()}
        launchPending
      />,
    )

    expect(screen.getByRole('button', { name: 'Launching...' })).toBeInTheDocument()
  })

  it('shows no-template warning when noTemplateWarning is true', () => {
    renderWithQuery(
      <DeployDialogContent
        product={product}
        valuesSchemaJson={null}
        initialValuesJson={null}
        onChange={vi.fn()}
        noTemplateWarning
      />,
    )

    expect(screen.getByText('This product has no template configured yet.')).toBeInTheDocument()
  })

  it('shows loading state', () => {
    renderWithQuery(
      <DeployDialogContent
        product={product}
        valuesSchemaJson={null}
        initialValuesJson={null}
        onChange={vi.fn()}
        loading
      />,
    )

    expect(screen.getByText('Loading...')).toBeInTheDocument()
  })

  it('shows form error alert', () => {
    renderWithQuery(
      <DeployDialogContent
        product={product}
        valuesSchemaJson={null}
        initialValuesJson={null}
        onChange={vi.fn()}
        formError="Something went wrong"
      />,
    )

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })
})
