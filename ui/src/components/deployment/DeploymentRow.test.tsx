import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ApiError } from '../../api/client'
import type { Deployment, DeploymentDatabase } from '../../api/types'
import { DeploymentRow } from './DeploymentRow'

const getDeploymentDatabaseMock = vi.fn()
const getDeploymentSftpMock = vi.fn()

vi.mock('../../api/endpoints', () => ({
  getDeploymentDatabase: (...args: unknown[]) => getDeploymentDatabaseMock(...args),
  getDeploymentSftp: (...args: unknown[]) => getDeploymentSftpMock(...args),
}))

const DETAILS: DeploymentDatabase = {
  host: 'pooler.internal',
  port: 6432,
  database: 'dpl_0f2c',
  role: 'dpl_0f2c',
  password: 'hunter2',
  password_withheld: false,
  quota_state: 'ok',
  allowance_bytes: 100 * 1024 ** 2,
  size_bytes: null,
  measured_at: null,
}

function deployment(status: Deployment['status']): Deployment {
  return {
    id: 'd1',
    desired_template_id: 1,
    hostname: 'app.example.test',
    user_id: 1,
    created_at: '2026-08-01T00:00:00Z',
    user: { id: 1, email: 'o@example.com', is_admin: false, created_at: '2026-08-01T00:00:00Z' },
    desired_template: { id: 1, product: { id: 1, name: 'Immich' } } as Deployment['desired_template'],
    name: 'app',
    namespace: 'ns',
    status,
    generation: 2,
  }
}

function renderRow(status: Deployment['status'], { expand = true } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui = (dep: Deployment) => (
    <QueryClientProvider client={client}>
      <DeploymentRow deployment={dep} userId={1} deletePending={false} onEdit={vi.fn()} onDelete={vi.fn()} />
    </QueryClientProvider>
  )
  const result = render(ui(deployment(status)))
  // The access actions live in the expanded row.
  if (expand) fireEvent.click(screen.getByRole('button', { expanded: false }))
  return { ...result, settle: () => result.rerender(ui(deployment('ready'))) }
}

beforeEach(() => {
  getDeploymentDatabaseMock.mockReset()
  getDeploymentSftpMock.mockReset()
  getDeploymentSftpMock.mockRejectedValue(new ApiError('no sftp', 404))
})

describe('DeploymentRow access requests', () => {
  it('asks for nothing until the row is expanded', async () => {
    getDeploymentDatabaseMock.mockResolvedValue(DETAILS)
    renderRow('ready', { expand: false })
    await act(async () => {})

    expect(getDeploymentDatabaseMock).not.toHaveBeenCalled()
    expect(getDeploymentSftpMock).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { expanded: false }))

    expect(await screen.findByRole('button', { name: /database/i })).toBeInTheDocument()
    expect(getDeploymentDatabaseMock).toHaveBeenCalledTimes(1)
    expect(getDeploymentSftpMock).toHaveBeenCalledTimes(1)
  })
})

describe('DeploymentRow database action', () => {
  it('offers no Database action when the deployment has no database', async () => {
    getDeploymentDatabaseMock.mockRejectedValue(new ApiError('no database', 404))
    renderRow('ready')

    await waitFor(() => expect(getDeploymentDatabaseMock).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /database/i })).not.toBeInTheDocument()
  })

  it('offers it once the details resolve', async () => {
    getDeploymentDatabaseMock.mockResolvedValue(DETAILS)
    renderRow('ready')

    expect(await screen.findByRole('button', { name: /database/i })).toBeInTheDocument()
  })

  it('picks the details up when a transitional deployment settles', async () => {
    // Provisioning: the database is not there yet, which is the deployment's
    // own state rather than a state of the database.
    getDeploymentDatabaseMock.mockRejectedValue(new ApiError('no database', 404))
    const { settle } = renderRow('provisioning')

    await waitFor(() => expect(getDeploymentDatabaseMock).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /database/i })).not.toBeInTheDocument()

    getDeploymentDatabaseMock.mockResolvedValue(DETAILS)
    settle()

    expect(await screen.findByRole('button', { name: /database/i })).toBeInTheDocument()
  })
})
