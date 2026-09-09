import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ClaimSubdomain, labelFromEmail } from './ClaimSubdomain'

const checkHostnameMock = vi.fn()
const claimSubdomainMock = vi.fn()

vi.mock('../../api/endpoints', () => ({
  checkHostname: (...args: unknown[]) => checkHostnameMock(...args),
  claimSubdomain: (...args: unknown[]) => claimSubdomainMock(...args),
}))

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>
}

function renderClaim(overrides: Partial<Parameters<typeof ClaimSubdomain>[0]> = {}) {
  const props = {
    domain: 'freepod.eu',
    email: 'ada.lovelace@example.com',
    onDismiss: vi.fn(),
    onClaimed: vi.fn(),
    ...overrides,
  }
  render(wrap(<ClaimSubdomain {...props} />))
  return props
}

describe('labelFromEmail', () => {
  it.each([
    ['ada.lovelace@example.com', 'adalovelace'],
    ['Ada_Lovelace@example.com', 'adalovelace'],
    ['-ada-@example.com', 'ada'],
  ])('derives a label from %s', (email, expected) => {
    expect(labelFromEmail(email)).toBe(expected)
  })
})

describe('ClaimSubdomain', () => {
  beforeEach(() => {
    checkHostnameMock.mockReset()
    claimSubdomainMock.mockReset()
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })) as unknown as typeof window.matchMedia
  })

  it('states both consequences before anything is claimed', () => {
    checkHostnameMock.mockResolvedValue({ fqdn: '', usable: true, reason: null })
    renderClaim()

    expect(screen.getByText(/It's permanent\./)).toBeInTheDocument()
    expect(screen.getByText(/It's public\./)).toBeInTheDocument()
    expect(screen.getByText(/certificate logs/)).toBeInTheDocument()
  })

  it('prefills from the email local part', () => {
    checkHostnameMock.mockResolvedValue({ fqdn: '', usable: true, reason: null })
    renderClaim()

    expect(screen.getByLabelText('Your domain name')).toHaveValue('adalovelace')
  })

  it('shows an unavailable prefill as refused, choosing no substitute', async () => {
    checkHostnameMock.mockResolvedValue({ fqdn: '', usable: false, reason: 'claimed' })
    renderClaim()

    await waitFor(() =>
      expect(screen.getByText('Taken. Try adding a word or a number.')).toBeInTheDocument(),
    )
    expect(screen.getByLabelText('Your domain name')).toHaveValue('adalovelace')
    expect(screen.getByRole('button', { name: 'Claim this name' })).toBeDisabled()
  })

  it('claims only through a confirmation showing the whole name, and no app label', async () => {
    checkHostnameMock.mockResolvedValue({ fqdn: '', usable: true, reason: null })
    claimSubdomainMock.mockResolvedValue({ subdomain: 'adalovelace', fqdn: 'adalovelace.freepod.eu', domain: 'freepod.eu' })
    renderClaim()

    const claim = await screen.findByRole('button', { name: 'Claim this name' })
    await waitFor(() => expect(claim).toBeEnabled())
    fireEvent.click(claim)

    expect(screen.getByText('adalovelace.freepod.eu')).toBeInTheDocument()
    expect(screen.queryByText('your app')).not.toBeInTheDocument()
    expect(claimSubdomainMock).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Yes, claim it' }))
    await waitFor(() => expect(claimSubdomainMock).toHaveBeenCalledWith('adalovelace'))
  })

  it('does not demand the name be retyped', async () => {
    checkHostnameMock.mockResolvedValue({ fqdn: '', usable: true, reason: null })
    renderClaim()

    const claim = await screen.findByRole('button', { name: 'Claim this name' })
    await waitFor(() => expect(claim).toBeEnabled())
    fireEvent.click(claim)

    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('goes back with the typed label intact', async () => {
    checkHostnameMock.mockResolvedValue({ fqdn: '', usable: true, reason: null })
    renderClaim()

    const input = screen.getByLabelText('Your domain name')
    fireEvent.change(input, { target: { value: 'grace' } })
    const claim = screen.getByRole('button', { name: 'Claim this name' })
    await waitFor(() => expect(claim).toBeEnabled())
    fireEvent.click(claim)

    fireEvent.click(screen.getByRole('button', { name: 'Go back' }))

    expect(screen.getByLabelText('Your domain name')).toHaveValue('grace')
  })

  it('stays put when the claim loses a race', async () => {
    const { ApiError } = await import('../../api/client')
    checkHostnameMock.mockResolvedValue({ fqdn: '', usable: true, reason: null })
    claimSubdomainMock.mockRejectedValue(new ApiError('taken', 409, 'subdomain_taken'))
    const props = renderClaim()

    const claim = await screen.findByRole('button', { name: 'Claim this name' })
    await waitFor(() => expect(claim).toBeEnabled())
    fireEvent.click(claim)
    fireEvent.click(screen.getByRole('button', { name: 'Yes, claim it' }))

    await waitFor(() =>
      expect(screen.getAllByText('Taken. Try adding a word or a number.').length).toBeGreaterThan(0),
    )
    expect(props.onDismiss).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Your domain name')).toHaveValue('adalovelace')
  })
})

describe('ClaimSubdomain, by context', () => {
  beforeEach(() => {
    checkHostnameMock.mockReset()
    checkHostnameMock.mockResolvedValue({ fqdn: '', usable: true, reason: null })
  })

  it('shows no application label when choosing the account address', () => {
    renderClaim({ context: 'account' })

    expect(screen.queryByText('your app')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '↻ again' })).not.toBeInTheDocument()
    expect(screen.getByText('.freepod.eu')).toBeInTheDocument()
  })

  it('is ready to type into on the dashboard', () => {
    renderClaim({ context: 'account', autoSelect: true })

    const input = screen.getByLabelText('Your domain name') as HTMLInputElement
    expect(input).toHaveFocus()
    expect(input.selectionEnd).toBe(input.value.length)
  })

  it('shows the whole deployment hostname on the deploy path', () => {
    renderClaim({ context: 'deploy' })

    expect(screen.getAllByText('your app').length).toBeGreaterThan(0)
  })

  it('asks a different question in each context', () => {
    const { unmount } = render(
      wrap(<ClaimSubdomain domain="freepod.eu" email="a@b.com" onDismiss={vi.fn()} context="account" />),
    )
    expect(screen.getByText(/Your own corner of Freepod/)).toBeInTheDocument()
    unmount()

    renderClaim({ context: 'deploy' })
    expect(
      screen.getByText(
        'Your application will then get a name underneath this personal subdomain name.',
      ),
    ).toBeInTheDocument()
  })
})
