import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { UsersPanel } from './UsersPanel'
import type { Deployment, ProductTemplate, User } from '../api/types'

const listUsersMock = vi.fn()
const listAllDeploymentsMock = vi.fn()

vi.mock('../api/endpoints', () => ({
  listUsers: (...args: unknown[]) => listUsersMock(...args),
  listAllDeployments: (...args: unknown[]) => listAllDeploymentsMock(...args),
}))

vi.mock('../state/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 99, email: 'admin@example.com', is_admin: true, created_at: '2026-01-01T00:00:00Z' },
    loading: false,
    email: 'admin@example.com',
    setEmail: vi.fn(),
  }),
}))

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <UsersPanel />
    </QueryClientProvider>,
  )
}

const users: User[] = [
  { id: 1, email: 'alice@example.com', is_admin: false, subdomain: 'alice', wildcard_domain: '*.alice.freepod.eu', created_at: '2026-01-01T00:00:00Z' },
  { id: 2, email: 'bob@example.com', is_admin: true, subdomain: null, wildcard_domain: null, created_at: '2026-02-01T00:00:00Z' },
  { id: 3, email: 'carol@example.com', is_admin: false, created_at: '2026-03-01T00:00:00Z' },
]

const template: ProductTemplate = {
  id: 1,
  product_id: 1,
  chart_ref: 'registry.example.com/charts/app',
  chart_version: '1.0.0',
  created_at: '2026-01-01T00:00:00Z',
  product: {
    id: 1,
    name: 'TestApp',
    visibility: 'public',
    curated: false,
    created_at: '2026-01-01T00:00:00Z',
  },
}

let depSeq = 0
const makeDeployment = (userId: number): Deployment => {
  depSeq += 1
  return {
    id: `dep-${depSeq}`,
    user_id: userId,
    hostname: null,
    desired_template_id: template.id,
    user_values_json: null,
    created_at: '2026-01-02T00:00:00Z',
    user: users.find((u) => u.id === userId)!,
    desired_template: template,
    applied_template: null,
    subscription_id: null,
    subscription: null,
    name: `dep-${depSeq}`,
    namespace: `user-${userId}`,
    status: 'ready',
  }
}

const dataRows = () => screen.getAllByRole('row').slice(1)
const rowEmails = () =>
  dataRows().map((row) => row.querySelector('[data-field="email"]')?.textContent ?? '')
const rowCell = (email: string, field: string) => {
  const row = screen.getByText(email).closest('[role="row"]')!
  return row.querySelector(`[data-field="${field}"]`)?.textContent ?? ''
}
const columnHeader = (field: string) =>
  screen.getByText(field, { selector: '[role="columnheader"] div' }).closest('[role="columnheader"]') as HTMLElement

describe('UsersPanel', () => {
  it('renders one row per user with id, email, admin status, wildcard domain, and join date', async () => {
    listUsersMock.mockResolvedValue(users)
    listAllDeploymentsMock.mockResolvedValue([])
    renderPanel()

    expect(await screen.findByText('alice@example.com')).toBeInTheDocument()
    expect(screen.getByText('bob@example.com')).toBeInTheDocument()
    expect(screen.getByText('carol@example.com')).toBeInTheDocument()

    expect(rowCell('alice@example.com', 'id')).toBe('1')
    expect(rowCell('bob@example.com', 'id')).toBe('2')
    expect(rowCell('bob@example.com', 'is_admin')).toBe('Yes')
    expect(rowCell('alice@example.com', 'is_admin')).toBe('No')
    expect(rowCell('alice@example.com', 'wildcard_domain')).toBe('*.alice.freepod.eu')
    expect(rowCell('bob@example.com', 'wildcard_domain')).toBe('')
    expect(rowCell('alice@example.com', 'created_at')).toMatch(/2026-01-01/)
  })

  it('shows the deployment count per user, zero for users without deployments', async () => {
    listUsersMock.mockResolvedValue(users)
    listAllDeploymentsMock.mockResolvedValue([makeDeployment(1), makeDeployment(1), makeDeployment(2)])
    renderPanel()

    await screen.findByText('alice@example.com')
    expect(rowCell('alice@example.com', 'deployment_count')).toBe('2')
    expect(rowCell('bob@example.com', 'deployment_count')).toBe('1')
    expect(rowCell('carol@example.com', 'deployment_count')).toBe('0')
  })

  it('sorts by join date descending by default', async () => {
    listUsersMock.mockResolvedValue(users)
    listAllDeploymentsMock.mockResolvedValue([])
    renderPanel()

    await screen.findByText('alice@example.com')
    expect(rowEmails()).toEqual(['carol@example.com', 'bob@example.com', 'alice@example.com'])
  })

  it('re-sorts when a column header is clicked', async () => {
    listUsersMock.mockResolvedValue(users)
    listAllDeploymentsMock.mockResolvedValue([])
    renderPanel()

    await screen.findByText('alice@example.com')
    fireEvent.click(columnHeader('Email'))
    await waitFor(() =>
      expect(rowEmails()).toEqual(['alice@example.com', 'bob@example.com', 'carol@example.com']),
    )
  })

  it('filters rows by email substring, case-insensitively', async () => {
    listUsersMock.mockResolvedValue(users)
    listAllDeploymentsMock.mockResolvedValue([])
    renderPanel()

    const search = await screen.findByPlaceholderText('Search by email')
    fireEvent.change(search, { target: { value: 'BOB' } })
    await waitFor(() => expect(screen.getByText('bob@example.com')).toBeInTheDocument())
    expect(screen.queryByText('alice@example.com')).not.toBeInTheDocument()
    expect(screen.queryByText('carol@example.com')).not.toBeInTheDocument()

    fireEvent.change(search, { target: { value: '' } })
    await waitFor(() => expect(screen.getByText('alice@example.com')).toBeInTheDocument())
    expect(screen.getByText('carol@example.com')).toBeInTheDocument()
  })

  it('paginates with the default page size', async () => {
    const manyUsers: User[] = Array.from({ length: 120 }, (_, i) => ({
      id: i + 1,
      email: `user${String(i + 1).padStart(3, '0')}@example.com`,
      is_admin: false,
      created_at: '2026-01-01T00:00:00Z',
    }))
    listUsersMock.mockResolvedValue(manyUsers)
    listAllDeploymentsMock.mockResolvedValue([])
    renderPanel()

    await screen.findByText('user001@example.com')
    expect(screen.getByText('1–100 of 120')).toBeInTheDocument()
    expect(dataRows()).toHaveLength(100)

    fireEvent.click(screen.getByRole('button', { name: 'Go to next page' }))
    await waitFor(() => expect(screen.getByText('101–120 of 120')).toBeInTheDocument())
    expect(dataRows()).toHaveLength(20)
  })
})
