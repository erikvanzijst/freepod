import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DeploymentDialog } from './DeploymentDialog'
import type { Deployment, Product, ProductTemplate } from '../api/types'

const getDeploymentMock = vi.fn()
const listTemplatesMock = vi.fn()
const updateDeploymentMock = vi.fn()

vi.mock('../api/endpoints', () => ({
  getDeployment: (...args: unknown[]) => getDeploymentMock(...args),
  listTemplates: (...args: unknown[]) => listTemplatesMock(...args),
  updateDeployment: (...args: unknown[]) => updateDeploymentMock(...args),
  deleteDeployment: vi.fn(),
  getDeploymentSftp: vi.fn().mockResolvedValue(null),
  getDeploymentDatabase: vi.fn().mockResolvedValue(null),
  getMySubdomain: vi.fn().mockResolvedValue({ subdomain: 'erik', fqdn: 'erik.freepod.eu', domain: 'freepod.eu' }),
  getCnameTarget: vi.fn().mockResolvedValue(''),
  checkHostname: vi.fn().mockResolvedValue({ fqdn: '', usable: true, reason: null }),
}))

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({
    // As in main.tsx: a nonzero staleTime is what makes initialData count as fresh.
    defaultOptions: { queries: { retry: false, staleTime: 5_000 }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const product: Product = {
  id: 7,
  name: 'PhotoPrism',
  template_id: 169,
  visibility: 'public',
  curated: true,
  created_at: '2026-09-20T00:00:00Z',
}

const password = {
  type: 'string',
  title: 'Password',
  'x-caelus-target': 'runtime',
  'x-caelus-sensitive': true,
}

// The template the deployment was created on: no username, and a key the
// canonical template no longer declares.
const appliedTemplate: ProductTemplate = {
  id: 123,
  product_id: 7,
  chart_ref: 'oci://registry/photoprism',
  chart_version: '0.1.2',
  values_schema_json: {
    type: 'object',
    additionalProperties: false,
    properties: {
      host: { type: 'string', title: 'Hostname', minLength: 1 },
      legacy: { type: 'string', title: 'Legacy' },
      PHOTOPRISM_ADMIN_PASSWORD: password,
    },
    required: ['host', 'PHOTOPRISM_ADMIN_PASSWORD'],
  },
  created_at: '2026-09-20T00:00:00Z',
  product,
}

const canonicalTemplate: ProductTemplate = {
  ...appliedTemplate,
  id: 169,
  chart_version: '0.1.5',
  values_schema_json: {
    type: 'object',
    additionalProperties: false,
    properties: {
      host: { type: 'string', title: 'Hostname', minLength: 1 },
      admin: {
        type: 'object',
        additionalProperties: false,
        properties: {
          username: { type: 'string', title: 'Username', minLength: 2, default: 'admin' },
        },
        required: ['username'],
      },
      PHOTOPRISM_ADMIN_PASSWORD: password,
    },
    required: ['host', 'admin', 'PHOTOPRISM_ADMIN_PASSWORD'],
  },
  created_at: '2026-09-30T00:00:00Z',
}

function makeDeployment(applied: ProductTemplate): Deployment {
  return {
    id: '00000000-0000-0000-0000-00000000002a',
    user_id: 3,
    desired_template_id: applied.id,
    name: 'photoprism-abc123',
    namespace: 'photoprism-fred-123456789',
    hostname: 'prism.fred.freepod.eu',
    user_values_json: { host: 'prism.fred.freepod.eu', legacy: 'x' },
    desired_template: applied,
    applied_template: { ...applied, product },
    status: 'ready',
    generation: 1,
    created_at: '2026-09-20T00:00:00Z',
    user: { id: 3, email: 'fred@example.com', is_admin: false, created_at: '2026-01-01T00:00:00Z' },
  }
}

describe('DeploymentDialog', () => {
  beforeEach(() => {
    getDeploymentMock.mockReset()
    listTemplatesMock.mockReset()
    updateDeploymentMock.mockReset()
  })

  it('upgrades against the canonical schema without needing the stored secret', async () => {
    const deployment = makeDeployment(appliedTemplate)
    getDeploymentMock.mockResolvedValue({
      ...deployment,
      vars: {
        PHOTOPRISM_ADMIN_PASSWORD: {
          sensitive: true,
          updated_at: '2026-09-20T00:00:00Z',
          updated_by: { id: 3 },
        },
      },
    })
    listTemplatesMock.mockResolvedValue([appliedTemplate, canonicalTemplate])
    updateDeploymentMock.mockResolvedValue({ ...deployment, status: 'provisioning' })

    renderWithQuery(<DeploymentDialog deployment={deployment} onClose={vi.fn()} />)

    // The field the canonical template newly requires, prefilled from its default.
    const username = await screen.findByRole('textbox', { name: /username/i })
    expect(username).toHaveValue('admin')
    expect(screen.queryByRole('textbox', { name: /legacy/i })).not.toBeInTheDocument()

    const upgrade = screen.getByRole('button', { name: 'Upgrade to #169' })
    await waitFor(() => expect(upgrade).toBeEnabled())
    fireEvent.click(upgrade)

    await waitFor(() => expect(updateDeploymentMock).toHaveBeenCalled())
    const [userId, deploymentId, payload] = updateDeploymentMock.mock.calls[0]
    expect(userId).toBe(3)
    expect(deploymentId).toBe(deployment.id)
    expect(payload.desired_template_id).toBe(169)
    expect(payload.user_values_json).toEqual({
      host: 'prism.fred.freepod.eu',
      admin: { username: 'admin' },
    })
    expect(payload.vars?.PHOTOPRISM_ADMIN_PASSWORD?.value).toBeUndefined()
  })

  it('stays read-only on the applied template when up to date', async () => {
    const current = { ...canonicalTemplate }
    const deployment = makeDeployment(current)
    deployment.user_values_json = { host: 'prism.fred.freepod.eu', admin: { username: 'fred' } }
    getDeploymentMock.mockResolvedValue(deployment)

    renderWithQuery(<DeploymentDialog deployment={deployment} onClose={vi.fn()} />)

    expect(await screen.findByRole('button', { name: 'Up to date' })).toBeDisabled()
    expect(listTemplatesMock).not.toHaveBeenCalled()
  })
})
