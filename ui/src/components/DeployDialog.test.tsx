import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { DeployDialog } from './DeployDialog'
import type { Deployment, Product, ProductTemplate } from '../api/types'

const listTemplatesMock = vi.fn()
const listPlansMock = vi.fn()
const createDeploymentMock = vi.fn()
const updateDeploymentMock = vi.fn()
const checkHostnameMock = vi.fn()
const getMySubdomainMock = vi.fn()
// Default: user has NOT accepted the Terms -> checkbox is shown. Individual
// tests override to simulate an already-accepted user.
const getTosAcceptanceMock = vi.fn().mockResolvedValue({ version: null, accepted_at: null })
const recordTosAcceptanceMock = vi.fn().mockResolvedValue({ version: '2026-07-01', accepted_at: '2026-07-01T00:00:00Z' })

vi.mock('../api/endpoints', () => ({
  listTemplates: (...args: unknown[]) => listTemplatesMock(...args),
  listPlans: (...args: unknown[]) => listPlansMock(...args),
  createDeployment: (...args: unknown[]) => createDeploymentMock(...args),
  updateDeployment: (...args: unknown[]) => updateDeploymentMock(...args),
  checkHostname: (...args: unknown[]) => checkHostnameMock(...args),
  getMySubdomain: (...args: unknown[]) => getMySubdomainMock(...args),
  getCnameTarget: vi.fn().mockResolvedValue(''),
  getTosAcceptance: (...args: unknown[]) => getTosAcceptanceMock(...args),
  recordTosAcceptance: (...args: unknown[]) => recordTosAcceptanceMock(...args),
}))

const freePlan = {
  id: 1,
  name: 'Free',
  product_id: 1,
  template_id: 100,
  sort_order: 1000,
  created_at: '2026-01-01T00:00:00Z',
  template: {
    id: 100,
    plan_id: 1,
    price_cents: 0,
    billing_interval: 'monthly',
    storage_bytes: 0,
    description: 'Everything for free',
    created_at: '2026-01-01T00:00:00Z',
  },
}

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const helloWorld: Product = {
  id: 1,
  name: 'Hello World',
  description: 'The obligatory hello world',
  template_id: 10,
  icon_url: null,
  visibility: 'public',
  curated: false,
  created_at: '2026-01-01T00:00:00Z',
}

const helloTemplate = {
  id: 10,
  product_id: 1,
  chart_ref: 'oci://registry/hello',
  chart_version: '0.1.0',
  system_values_json: null,
  values_schema_json: {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    type: 'object',
    properties: {
      hostname: {
        title: 'hostname',
        type: 'string',
        minLength: 1,
      },
    },
    required: ['hostname'],
    additionalProperties: false,
  },
  created_at: '2026-01-01T00:00:00Z',
}

describe('DeployDialog', () => {
  it('renders product name and description in the header', async () => {
    listTemplatesMock.mockResolvedValue([helloTemplate])
    listPlansMock.mockResolvedValue([freePlan])
    getMySubdomainMock.mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' })

    renderWithQuery(
      <DeployDialog product={helloWorld} userId={1} onClose={vi.fn()} />,
    )

    expect(screen.getByText('Hello World')).toBeInTheDocument()
    expect(screen.getByText('The obligatory hello world')).toBeInTheDocument()
  })

  it('shows Cancel and disabled Launch buttons', async () => {
    listTemplatesMock.mockResolvedValue([helloTemplate])
    listPlansMock.mockResolvedValue([freePlan])
    getMySubdomainMock.mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' })

    renderWithQuery(
      <DeployDialog product={helloWorld} userId={1} onClose={vi.fn()} />,
    )

    expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Launch' })).toBeDisabled()
    })
  })

  it('calls onClose when Cancel is clicked', async () => {
    listTemplatesMock.mockResolvedValue([helloTemplate])
    listPlansMock.mockResolvedValue([freePlan])
    getMySubdomainMock.mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' })
    const onClose = vi.fn()

    renderWithQuery(
      <DeployDialog product={helloWorld} userId={1} onClose={onClose} />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('shows warning when product has no template', async () => {
    const noTemplate: Product = { ...helloWorld, template_id: null }
    listTemplatesMock.mockResolvedValue([])
    getMySubdomainMock.mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' })

    renderWithQuery(
      <DeployDialog product={noTemplate} userId={1} onClose={vi.fn()} />,
    )

    await waitFor(() => {
      expect(screen.getByText('This product has no template configured yet.')).toBeInTheDocument()
    })
  })

  it('enables Launch when hostname is valid and submits deployment', async () => {
    listTemplatesMock.mockResolvedValue([helloTemplate])
    listPlansMock.mockResolvedValue([freePlan])
    getMySubdomainMock.mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' })
    checkHostnameMock.mockResolvedValue({ fqdn: 'test.example.com', usable: true, reason: null })
    createDeploymentMock.mockResolvedValue({ deployment: { id: '1' }, checkout_url: null })
    const onClose = vi.fn()

    renderWithQuery(
      <DeployDialog product={helloWorld} userId={42} onClose={onClose} />,
    )

    // Wait for the template query to resolve and the form to render
    await waitFor(() => {
      expect(screen.getByText('Configure application values:')).toBeInTheDocument()
    })

    const hostnameInput = screen.getByRole('textbox', { name: /hostname/i })
    fireEvent.change(hostnameInput, { target: { value: 'test.example.com' } })

    // Launch stays disabled until the Terms of Service checkbox is checked.
    expect(screen.getByRole('button', { name: 'Launch' })).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox'))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Launch' })).toBeEnabled()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Launch' }))

    // First launch records ToS acceptance (with the displayed version) before
    // creating the deployment; the create payload carries no ToS field.
    await waitFor(() => {
      expect(recordTosAcceptanceMock).toHaveBeenCalledWith('2026-08-26')
    })
    await waitFor(() => {
      expect(createDeploymentMock).toHaveBeenCalledWith(42, {
        desired_template_id: 10,
        user_values_json: { hostname: 'test.example.com' },
        plan_template_id: 100,
      })
    })

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('already-accepted user sees no ToS checkbox and deploys without recording again', async () => {
    listTemplatesMock.mockResolvedValue([helloTemplate])
    listPlansMock.mockResolvedValue([freePlan])
    getMySubdomainMock.mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' })
    checkHostnameMock.mockResolvedValue({ fqdn: 'accepted.example.com', usable: true, reason: null })
    createDeploymentMock.mockResolvedValue({ deployment: { id: '1' }, checkout_url: null })
    // This user already accepted the current Terms.
    getTosAcceptanceMock.mockResolvedValueOnce({ version: '2026-07-01', accepted_at: '2026-07-01T00:00:00Z' })
    recordTosAcceptanceMock.mockClear()
    const onClose = vi.fn()

    renderWithQuery(
      <DeployDialog product={helloWorld} userId={7} onClose={onClose} />,
    )

    await waitFor(() => {
      expect(screen.getByText('Configure application values:')).toBeInTheDocument()
    })

    // No agreement checkbox is shown once the user has accepted.
    await waitFor(() => {
      expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    })

    const hostnameInput = screen.getByRole('textbox', { name: /hostname/i })
    fireEvent.change(hostnameInput, { target: { value: 'accepted.example.com' } })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Launch' })).toBeEnabled()
    })
    fireEvent.click(screen.getByRole('button', { name: 'Launch' }))

    await waitFor(() => {
      expect(createDeploymentMock).toHaveBeenCalledWith(7, {
        desired_template_id: 10,
        user_values_json: { hostname: 'accepted.example.com' },
        plan_template_id: 100,
      })
    })
    // No acceptance recorded — the user had already accepted.
    expect(recordTosAcceptanceMock).not.toHaveBeenCalled()
  })

  it('shows error alert on deployment failure', async () => {
    listTemplatesMock.mockResolvedValue([helloTemplate])
    listPlansMock.mockResolvedValue([freePlan])
    getMySubdomainMock.mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' })
    checkHostnameMock.mockResolvedValue({ fqdn: 'test.example.com', usable: true, reason: null })
    createDeploymentMock.mockRejectedValue(new Error('Server error'))

    renderWithQuery(
      <DeployDialog product={helloWorld} userId={1} onClose={vi.fn()} />,
    )

    await waitFor(() => {
      expect(screen.getByText('Configure application values:')).toBeInTheDocument()
    })

    const hostnameInput = screen.getByRole('textbox', { name: /hostname/i })
    fireEvent.change(hostnameInput, { target: { value: 'test.example.com' } })
    fireEvent.click(screen.getByRole('checkbox'))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Launch' })).toBeEnabled()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Launch' }))

    await waitFor(() => {
      expect(screen.getByText('Server error')).toBeInTheDocument()
    })
  })

  it('opening and closing the ToS modal preserves the entered hostname', async () => {
    listTemplatesMock.mockResolvedValue([helloTemplate])
    listPlansMock.mockResolvedValue([freePlan])
    getMySubdomainMock.mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' })
    checkHostnameMock.mockResolvedValue({ fqdn: 'keep.example.com', usable: true, reason: null })

    renderWithQuery(<DeployDialog product={helloWorld} userId={1} onClose={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('Configure application values:')).toBeInTheDocument()
    })

    const hostnameInput = screen.getByRole('textbox', { name: /hostname/i })
    fireEvent.change(hostnameInput, { target: { value: 'keep.example.com' } })

    // Open the ToS document from the agreement text.
    fireEvent.click(screen.getByRole('button', { name: 'Terms of Service' }))
    await waitFor(() => {
      expect(screen.getByText(/Effective date:/i)).toBeInTheDocument()
    })

    // Close it and confirm the deploy form kept the hostname. The background
    // dialog is aria-hidden while the modal is open and during its close
    // transition, so retry until the field is reachable again.
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() => {
      expect(screen.getByRole('textbox', { name: /hostname/i })).toHaveValue('keep.example.com')
    })
  })

  it('edit mode uses deployment template, not product canonical template', async () => {
    // The deployment was created with template 5, but the product's canonical
    // template has since moved to 10. The edit dialog must use template 5.
    const oldTemplate: ProductTemplate = {
      id: 5,
      product_id: 1,
      chart_ref: 'oci://registry/hello',
      chart_version: '0.0.9',
      system_values_json: null,
      values_schema_json: {
        $schema: 'https://json-schema.org/draft/2020-12/schema',
        type: 'object',
        properties: {
          hostname: {
            title: 'hostname',
            type: 'string',
            minLength: 1,
          },
        },
        required: ['hostname'],
        additionalProperties: false,
      },
      created_at: '2025-12-01T00:00:00Z',
      product: helloWorld,
    }

    const deployment: Deployment = {
      id: '00000000-0000-0000-0000-00000000002a',
      user_id: 1,
      desired_template_id: 5,
      name: 'hello-world-abc123',
      namespace: 'test-example-123456789',
      hostname: 'edit-test.example.com',
      user_values_json: { hostname: 'edit-test.example.com' },
      desired_template: oldTemplate,
      status: 'ready',
      generation: 1,
      created_at: '2026-01-15T00:00:00Z',
      user: { id: 1, email: 'test@example.com', is_admin: false, created_at: '2026-01-01T00:00:00Z' },
    }

    getMySubdomainMock.mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' })
    listTemplatesMock.mockClear()
    updateDeploymentMock.mockResolvedValue({ id: 42 })
    const onClose = vi.fn()

    renderWithQuery(
      <DeployDialog product={helloWorld} userId={1} onClose={onClose} deployment={deployment} />,
    )

    // The form should render using the deployment's template schema
    await waitFor(() => {
      expect(screen.getByText('Configure application values:')).toBeInTheDocument()
    })

    // Hostname should be pre-populated from deployment.user_values_json
    expect(screen.getByRole('textbox', { name: /hostname/i })).toHaveValue('edit-test.example.com')

    // Button should say "Update" not "Launch"
    const updateBtn = screen.getByRole('button', { name: 'Update' })
    expect(updateBtn).toBeEnabled()

    fireEvent.click(updateBtn)

    // Must send deployment's template ID (5), NOT the product's canonical (10)
    await waitFor(() => {
      expect(updateDeploymentMock).toHaveBeenCalledWith(1, '00000000-0000-0000-0000-00000000002a', {
        desired_template_id: 5,
        user_values_json: { hostname: 'edit-test.example.com' },
      })
    })

    // Should NOT have fetched templates (not needed in edit mode)
    expect(listTemplatesMock).not.toHaveBeenCalled()
  })
})
