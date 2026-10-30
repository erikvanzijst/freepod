import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { AccessEntry, AccessList } from '../../api/types'
import { AccessDialog } from './AccessDialog'

const getMock = vi.fn()
const addMock = vi.fn()
const removeMock = vi.fn()

vi.mock('../../api/endpoints', () => ({
  getDeploymentAccess: (...args: unknown[]) => getMock(...args),
  addDeploymentAccess: (...args: unknown[]) => addMock(...args),
  removeDeploymentAccess: (...args: unknown[]) => removeMock(...args),
}))

const ana: AccessEntry = { id: 'e-ana', email: 'ana@example.com', name: 'Ana Costa', created_at: '2026-10-01T10:00:00Z', bound_at: '2026-10-22T10:00:00Z' }
const jules: AccessEntry = { id: 'e-jules', email: 'jules@example.org', name: null, created_at: '2026-10-27T10:00:00Z', bound_at: null }

function list(entries: AccessEntry[]): AccessList {
  return { enabled: true, protocol: 'header', access: 'listed', owner_email: 'you@example.com', limit: 500, entries }
}

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AccessDialog userId={1} deploymentId="d1" hostname="cloud-yourname.freepod.app" appName="Nextcloud" onClose={vi.fn()} />
    </QueryClientProvider>,
  )
}

function people(count: number): AccessEntry[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `e${i}`,
    email: i % 2 ? `person${i}@example.com` : `sam${i}@example.org`,
    name: i % 3 ? `Person ${i}` : null,
    created_at: '2026-10-01T10:00:00Z',
    bound_at: i % 3 ? '2026-10-20T10:00:00Z' : null,
  }))
}

const field = () => screen.getByLabelText('Add someone by email')

beforeEach(() => {
  getMock.mockReset()
  addMock.mockReset()
  removeMock.mockReset()
})

describe('AccessDialog', () => {
  it('lists the owner first, then bound and unbound entries', async () => {
    getMock.mockResolvedValue(list([ana, jules]))
    renderDialog()
    expect(await screen.findByText('you@example.com · always has access')).toBeInTheDocument()
    expect(screen.getByText('Owner')).toBeInTheDocument()
    expect(screen.getByText('3 people can sign in')).toBeInTheDocument()
    expect(screen.getByText('Ana Costa')).toBeInTheDocument()
    expect(screen.getByText(/signed in Oct 22/)).toBeInTheDocument()
    expect(screen.getByText("Invited Oct 27 · hasn't signed in yet")).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove you@example.com' })).not.toBeInTheDocument()
    expect(screen.getByText(/We email everyone you add a link to Nextcloud/)).toBeInTheDocument()
    expect(screen.getByText(/can sign in to Nextcloud/)).toBeInTheDocument()
  })

  it('adds someone and clears the field', async () => {
    getMock.mockResolvedValue(list([]))
    addMock.mockResolvedValue({ ...jules })
    renderDialog()
    await screen.findByText('1 person can sign in')
    fireEvent.change(field(), { target: { value: 'jules@example.org' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(addMock).toHaveBeenCalledWith(1, 'd1', 'jules@example.org'))
    await waitFor(() => expect(field()).toHaveValue(''))
    expect(getMock).toHaveBeenCalledTimes(2)
  })

  it.each([
    ['access_duplicate', 'Jules@example.org', 'jules@example.org is already on the list.'],
    ['access_duplicate', 'You@Example.com', 'That is you. You always have access.'],
    ['access_invalid_email', 'ana@', 'Enter a full email address, like name@example.com.'],
    ['access_list_full', 'x@example.com', 'The list is full: it holds 500 people. Remove someone to add another.'],
    ['access_invitation_limit', 'x@example.com', 'You have sent 100 invitations in the past 24 hours.'],
  ])('keeps the address and explains a refusal (%s)', async (code, typed, message) => {
    getMock.mockResolvedValue(list([jules]))
    addMock.mockRejectedValue(new ApiError('You have sent 100 invitations in the past 24 hours.', code === 'access_invitation_limit' ? 429 : 409, code))
    renderDialog()
    await screen.findByText('jules@example.org')
    fireEvent.change(field(), { target: { value: typed } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(field()).toHaveValue(typed)
  })

  it('confirms a removal in the row, and only confirming removes', async () => {
    getMock.mockResolvedValue(list([ana, jules]))
    removeMock.mockResolvedValue(null)
    renderDialog()
    fireEvent.click(await screen.findByRole('button', { name: 'Remove ana@example.com' }))
    expect(screen.getByText('Remove Ana Costa?')).toBeInTheDocument()
    expect(screen.getByText(/lose access to Nextcloud within a minute/)).toBeInTheDocument()
    expect(screen.getByText(/What they stored there stays/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(removeMock).not.toHaveBeenCalled()
    expect(screen.queryByText('Remove Ana Costa?')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Remove ana@example.com' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(removeMock).toHaveBeenCalledWith(1, 'd1', 'e-ana'))
    expect(screen.queryByRole('button', { name: /undo/i })).not.toBeInTheDocument()
  })

  it('keeps the row and says why when a removal fails', async () => {
    getMock.mockResolvedValue(list([ana]))
    removeMock.mockRejectedValue(new ApiError('photos-erik.freepod.app could not be reached to sign this person out.', 502, 'access_logout_failed'))
    renderDialog()
    fireEvent.click(await screen.findByRole('button', { name: 'Remove ana@example.com' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be reached')
    expect(screen.getByText('Remove Ana Costa?')).toBeInTheDocument()
  })

  it('offers no search for a short list', async () => {
    getMock.mockResolvedValue(list(people(4)))
    renderDialog()
    await screen.findByText('5 people can sign in')
    expect(screen.queryByPlaceholderText('Search people')).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Filter' })).not.toBeInTheDocument()
  })

  it('searches and filters a long list, and counts the places used', async () => {
    getMock.mockResolvedValue(list(people(214)))
    renderDialog()
    const search = await screen.findByPlaceholderText('Search people')
    expect(screen.getByText('You (owner) always have access. 214 of 500 places used.')).toBeInTheDocument()
    expect(screen.getByText('you@example.com · always has access')).toBeInTheDocument()

    fireEvent.change(search, { target: { value: 'sam1' } })
    const matching = people(214).filter((p) => p.email.includes('sam1'))
    expect(await screen.findByText(`${matching.length} of 214 people match`)).toBeInTheDocument()
    expect(screen.queryByText('you@example.com · always has access')).not.toBeInTheDocument()
    const rows = within(screen.getByTestId('access-list')).getAllByRole('button', { name: /^Remove / })
    expect(rows).toHaveLength(matching.length)

    fireEvent.click(screen.getByRole('button', { name: 'Not yet' }))
    const notYet = matching.filter((p) => !p.bound_at)
    expect(await screen.findByText(`${notYet.length} of 214 people match`)).toBeInTheDocument()
  })

  it('shows the add field in view however long the list', async () => {
    getMock.mockResolvedValue(list(people(214)))
    renderDialog()
    await screen.findByPlaceholderText('Search people')
    expect(screen.getByTestId('access-list')).toHaveStyle({ overflowY: 'auto' })
    expect(field()).toBeInTheDocument()
  })
})
