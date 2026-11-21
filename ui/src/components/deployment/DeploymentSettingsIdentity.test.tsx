import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { Deployment, Product, ProductTemplate } from '../../api/types'
import { DeployDialog } from '../DeployDialog'

const updateDeploymentMock = vi.fn()
const getDeploymentMock = vi.fn()

vi.mock('../../api/endpoints', () => ({
  listTemplates: vi.fn(),
  listPlans: vi.fn(),
  createDeployment: vi.fn(),
  updateDeployment: (...args: unknown[]) => updateDeploymentMock(...args),
  getDeployment: (...args: unknown[]) => getDeploymentMock(...args),
  checkHostname: vi.fn().mockResolvedValue({ usable: true, reason: null }),
  getMyHandle: vi.fn(),
  getCnameTarget: vi.fn().mockResolvedValue(''),
  getTosAcceptance: vi.fn().mockResolvedValue({ version: '2026-07-01' }),
  recordTosAcceptance: vi.fn(),
}))

vi.mock('../image/cropImage', async (orig) => ({
  ...(await orig<typeof import('../image/cropImage')>()),
  cropImage: () => Promise.resolve(new Blob(['icon'], { type: 'image/png' })),
}))

URL.createObjectURL = vi.fn(() => 'blob:picked')
URL.revokeObjectURL = vi.fn()

vi.mock('../handle/useMyHandle', () => ({ useMyHandle: () => ({ data: undefined, isSuccess: true }) }))

const custom: Product = {
  id: 1,
  name: 'Custom user app',
  slug: 'custom',
  description: 'Your own code',
  template_id: 5,
  icon_url: '/api/static/icons/custom.png',
  visibility: 'public',
  curated: true,
  created_at: '2026-01-01T00:00:00Z',
}

const template: ProductTemplate = {
  id: 5,
  product_id: 1,
  chart_ref: 'oci://registry/custom',
  chart_version: '0.1.0',
  system_values_json: null,
  values_schema_json: {
    type: 'object',
    additionalProperties: false,
    properties: {
      hostname: { title: 'hostname', type: 'string', minLength: 1 },
      auth: {
        type: 'object',
        title: 'Sign in with Freepod',
        additionalProperties: false,
        properties: { enabled: { type: 'boolean', title: 'Sign in with Freepod' } },
      },
    },
    required: ['hostname'],
  },
  created_at: '2026-01-01T00:00:00Z',
  product: custom,
}

function deployment(overrides: Partial<Deployment> = {}): Deployment {
  return {
    id: 'd-1',
    user_id: 1,
    desired_template_id: 5,
    name: 'Arkanoid',
    description: null,
    icon_url: null,
    managed_fields: [],
    namespace: 'ns',
    hostname: 'arkanoid.example.com',
    user_values_json: { hostname: 'arkanoid.example.com', auth: { enabled: true } },
    desired_template: template,
    status: 'ready',
    power: { desired: 'running', applied: 'running' },
    generation: 2,
    created_at: '2026-01-15T00:00:00Z',
    user: { id: 1, email: 'o@example.com', is_admin: false, created_at: '2026-01-01T00:00:00Z' },
    ...overrides,
  }
}

function open(d: Deployment) {
  getDeploymentMock.mockResolvedValue(d)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <DeployDialog product={custom} userId={1} onClose={vi.fn()} deployment={d} />
    </QueryClientProvider>,
  )
}

const nameField = () => screen.getByRole('textbox', { name: /^name/i })

// Update waits for the hostname check, which runs for the stored hostname too.
async function clickUpdate() {
  const update = screen.getByRole('button', { name: 'Update' })
  await waitFor(() => expect(update).toBeEnabled())
  fireEvent.click(update)
}

beforeEach(() => {
  updateDeploymentMock.mockReset()
  updateDeploymentMock.mockImplementation((_u: number, _id: string, body: object) => Promise.resolve({ ...deployment(), ...body }))
})
afterEach(() => vi.clearAllMocks())

describe('Settings: the deployment identity', () => {
  it('sends a rename in the same update as the chart values', async () => {
    open(deployment())
    await waitFor(() => expect(nameField()).toHaveValue('Arkanoid'))
    fireEvent.change(nameField(), { target: { value: 'Arkanoid: Space Edition' } })
    await clickUpdate()
    await waitFor(() => expect(updateDeploymentMock).toHaveBeenCalledTimes(1))
    const [, , body] = updateDeploymentMock.mock.calls[0]
    expect(body).toMatchObject({
      desired_template_id: 5,
      name: 'Arkanoid: Space Edition',
      user_values_json: { hostname: 'arkanoid.example.com', auth: { enabled: true } },
    })
    expect(body).not.toHaveProperty('icon')
    expect(body).not.toHaveProperty('managed_fields')
  })

  it('leaves a setting the deployment never had out of a rename', async () => {
    open(deployment({ user_values_json: { hostname: 'arkanoid.example.com' } }))
    await waitFor(() => expect(nameField()).toHaveValue('Arkanoid'))
    fireEvent.change(nameField(), { target: { value: 'Breakout' } })
    await clickUpdate()
    await waitFor(() => expect(updateDeploymentMock).toHaveBeenCalledTimes(1))
    expect(updateDeploymentMock.mock.calls[0][2].user_values_json).toEqual({ hostname: 'arkanoid.example.com' })
  })

  it('sends a setting the deployment never had once it is changed', async () => {
    open(deployment({ user_values_json: { hostname: 'arkanoid.example.com' } }))
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Sign in with Freepod' }))
    await clickUpdate()
    await waitFor(() => expect(updateDeploymentMock).toHaveBeenCalledTimes(1))
    expect(updateDeploymentMock.mock.calls[0][2].user_values_json.auth).toEqual({ enabled: true })
  })

  it('resets an own icon to the product one with a null icon', async () => {
    open(deployment({ icon_url: '/api/static/icons/own.png' }))
    await waitFor(() => expect(screen.getByText('Your own icon')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(screen.getByText("Custom user app's icon (default)")).toBeInTheDocument()
    await clickUpdate()
    await waitFor(() => expect(updateDeploymentMock).toHaveBeenCalled())
    expect(updateDeploymentMock.mock.calls[0][2]).toMatchObject({ icon: null })
  })

  it('crops an uploaded icon and sends it as base64', async () => {
    open(deployment())
    await waitFor(() => expect(nameField()).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
    fireEvent.change(screen.getByTestId('image-file'), {
      target: { files: [new File(['x'], 'photo.jpg', { type: 'image/jpeg' })] },
    })
    const img = await screen.findByAltText('The picked image')
    Object.defineProperty(img, 'width', { value: 300 })
    Object.defineProperty(img, 'height', { value: 300 })
    fireEvent.load(img)
    fireEvent.click(screen.getByRole('button', { name: 'Use image' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Crop the icon' })).not.toBeInTheDocument())
    expect(await screen.findByText('Your own icon')).toBeInTheDocument()
    await clickUpdate()
    await waitFor(() => expect(updateDeploymentMock).toHaveBeenCalled())
    expect(updateDeploymentMock.mock.calls[0][2]).toMatchObject({ icon: btoa('icon') })
  })

  it('shows a name in use on the name field', async () => {
    updateDeploymentMock.mockRejectedValue(new ApiError('You already have a deployment named', 409, 'name_in_use'))
    open(deployment())
    await waitFor(() => expect(nameField()).toBeInTheDocument())
    fireEvent.change(nameField(), { target: { value: 'Pong' } })
    await clickUpdate()
    expect(await screen.findByText('You already have an app with this name.')).toBeInTheDocument()
    expect(nameField()).toHaveAttribute('aria-invalid', 'true')
  })
})

describe('Settings: fields managed by .freepod.json', () => {
  it('shows a managed sign-in setting read-only and sends it unchanged', async () => {
    open(deployment({ managed_fields: ['auth'], user_values_json: { hostname: 'arkanoid.example.com', auth: { enabled: true } } }))
    expect(await screen.findByText(/Sign in with Freepod is managed by/)).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Sign in with Freepod' })).toBeDisabled()
    await clickUpdate()
    await waitFor(() => expect(updateDeploymentMock).toHaveBeenCalled())
    const body = updateDeploymentMock.mock.calls[0][2]
    expect(body.user_values_json.auth).toEqual({ enabled: true })
    expect(body).not.toHaveProperty('managed_fields')
  })

  it('takes over a managed name after confirming', async () => {
    open(deployment({ managed_fields: ['name', 'auth'] }))
    expect(await screen.findByText(/Name is managed by/)).toBeInTheDocument()
    expect(nameField()).toHaveAttribute('readonly')
    const notice = screen.getByText(/Name is managed by/).closest('div')!
    fireEvent.click(within(notice).getByRole('button', { name: 'Take over' }))
    const dialog = await screen.findByRole('dialog', { name: /Edit Name here/ })
    expect(within(dialog).getByText(/puts its value back/)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Take over' }))
    await waitFor(() => expect(updateDeploymentMock).toHaveBeenCalledWith(1, 'd-1', { managed_fields: ['auth'] }))
    await waitFor(() => expect(nameField()).not.toHaveAttribute('readonly'))
  })
})
