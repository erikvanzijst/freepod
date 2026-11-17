import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { GitConnection, GitHubInstallation } from '../../api/types'
import { GitPanel } from './GitPanel'

const listGitConnectionsMock = vi.fn()
const startGitHubConnectMock = vi.fn()
const listGitHubInstallationsMock = vi.fn()
const disconnectGitHubMock = vi.fn()
const redirectToMock = vi.fn()

vi.mock('../../api/endpoints', () => ({
  listGitConnections: (...args: unknown[]) => listGitConnectionsMock(...args),
  startGitHubConnect: (...args: unknown[]) => startGitHubConnectMock(...args),
  listGitHubInstallations: (...args: unknown[]) => listGitHubInstallationsMock(...args),
  disconnectGitHub: (...args: unknown[]) => disconnectGitHubMock(...args),
}))

vi.mock('./redirect', () => ({ redirectTo: (url: string) => redirectToMock(url) }))

vi.mock('../../state/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 7, email: 'dev@example.com', is_admin: false, created_at: '2026-01-01T00:00:00Z' },
    loading: false,
    email: 'dev@example.com',
    setEmail: vi.fn(),
  }),
}))

const connection: GitConnection = {
  provider: 'github',
  host: 'github.com',
  account_id: '1001',
  login: 'alice',
  connected_at: '2026-11-17T10:00:00Z',
  expires_at: '2027-05-17T10:00:00Z',
}

const installation: GitHubInstallation = {
  id: 77,
  account: 'acme',
  account_type: 'Organization',
  repository_selection: 'selected',
  html_url: 'https://github.com/organizations/acme/settings/installations/77',
}

const links = {
  authorize_url: 'https://github.com/login/oauth/authorize?state=s',
  install_url: 'https://github.com/apps/freepod/installations/new?state=s',
}

function renderPanel(path = '/settings/git') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <GitPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  for (const mock of [
    listGitConnectionsMock,
    startGitHubConnectMock,
    listGitHubInstallationsMock,
    disconnectGitHubMock,
    redirectToMock,
  ]) {
    mock.mockReset()
  }
  startGitHubConnectMock.mockResolvedValue(links)
})

describe('GitPanel', () => {
  it('sends an unconnected account to GitHub to authorize the app', async () => {
    listGitConnectionsMock.mockResolvedValue([])
    renderPanel()

    fireEvent.click(await screen.findByRole('button', { name: /connect github/i }))

    await waitFor(() => expect(redirectToMock).toHaveBeenCalledWith(links.authorize_url))
    expect(startGitHubConnectMock).toHaveBeenCalledWith(7)
    expect(listGitHubInstallationsMock).not.toHaveBeenCalled()
  })

  it('explains when this environment has no GitHub app', async () => {
    listGitConnectionsMock.mockResolvedValue([])
    startGitHubConnectMock.mockRejectedValue(new ApiError('unavailable', 503, 'github_unavailable'))
    renderPanel()

    fireEvent.click(await screen.findByRole('button', { name: /connect github/i }))

    expect(await screen.findByText(/not available on this freepod environment/i)).toBeInTheDocument()
    expect(redirectToMock).not.toHaveBeenCalled()
  })

  it('shows the connected account and its installations', async () => {
    listGitConnectionsMock.mockResolvedValue([connection])
    listGitHubInstallationsMock.mockResolvedValue([installation])
    renderPanel()

    expect(await screen.findByRole('link', { name: 'alice' })).toHaveAttribute(
      'href',
      'https://github.com/alice',
    )
    expect(await screen.findByText('acme')).toBeInTheDocument()
    expect(screen.getByText('Selected repositories')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /configure/i })).toHaveAttribute('href', installation.html_url)
  })

  it('installs the app on another account', async () => {
    listGitConnectionsMock.mockResolvedValue([connection])
    listGitHubInstallationsMock.mockResolvedValue([])
    renderPanel()

    fireEvent.click(await screen.findByRole('button', { name: /add account/i }))

    await waitFor(() => expect(redirectToMock).toHaveBeenCalledWith(links.install_url))
  })

  it('disconnects after confirming', async () => {
    listGitConnectionsMock.mockResolvedValueOnce([connection]).mockResolvedValue([])
    listGitHubInstallationsMock.mockResolvedValue([installation])
    disconnectGitHubMock.mockResolvedValue(null)
    renderPanel()

    fireEvent.click(await screen.findByRole('button', { name: /^disconnect$/i }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('alice')
    fireEvent.click(screen.getAllByRole('button', { name: /^disconnect$/i }).at(-1)!)

    await waitFor(() => expect(disconnectGitHubMock).toHaveBeenCalledWith(7))
    expect(await screen.findByRole('button', { name: /connect github/i })).toBeInTheDocument()
  })

  it('reports what GitHub sent back', async () => {
    listGitConnectionsMock.mockResolvedValue([])
    renderPanel('/settings/git?github_error=github_account_in_use')

    expect(
      await screen.findByText(/already connected to another freepod account/i),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /close/i }))
    await waitFor(() =>
      expect(screen.queryByText(/already connected to another freepod account/i)).not.toBeInTheDocument(),
    )
  })

  it('confirms a connection GitHub sent back', async () => {
    listGitConnectionsMock.mockResolvedValue([connection])
    listGitHubInstallationsMock.mockResolvedValue([])
    renderPanel('/settings/git?github=connected')

    expect(await screen.findByText(/your account is connected to github/i)).toBeInTheDocument()
  })

  it('starts authorizing at once when a link from the CLI asks', async () => {
    listGitConnectionsMock.mockResolvedValue([])
    renderPanel('/settings/git?connect=github')

    await waitFor(() => expect(redirectToMock).toHaveBeenCalledWith(links.authorize_url))
    expect(startGitHubConnectMock).toHaveBeenCalledTimes(1)
  })

  it('does not reconnect an account that is already connected', async () => {
    listGitConnectionsMock.mockResolvedValue([connection])
    listGitHubInstallationsMock.mockResolvedValue([])
    renderPanel('/settings/git?connect=github')

    expect(await screen.findByRole('link', { name: 'alice' })).toBeInTheDocument()
    expect(startGitHubConnectMock).not.toHaveBeenCalled()
  })
})
