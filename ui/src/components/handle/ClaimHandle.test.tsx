import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { ClaimHandle, handleFromEmail } from './ClaimHandle'

// The as-you-type check is the dry run; the claim itself is the same call without it.
const dryRunMock = vi.fn()
const claimHandleMock = vi.fn()

vi.mock('../../api/endpoints', () => ({
  claimHandle: (handle: string, options?: { dryRun?: boolean }) =>
    options?.dryRun ? dryRunMock(handle) : claimHandleMock(handle),
}))

const AVAILABLE = { handle: 'adalovelace', suffix: '-adalovelace.freepod.app', domain: 'freepod.app' }

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>
}

function renderClaim(overrides: Partial<Parameters<typeof ClaimHandle>[0]> = {}) {
  const props = {
    domain: 'freepod.app',
    email: 'ada.lovelace@example.com',
    onDismiss: vi.fn(),
    onClaimed: vi.fn(),
    ...overrides,
  }
  render(wrap(<ClaimHandle {...props} />))
  return props
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('handleFromEmail', () => {
  it.each([
    ['ada.lovelace@example.com', 'adalovelace'],
    ['Ada_Lovelace@example.com', 'adalovelace'],
    ['-ada-lovelace-@example.com', 'adalovelace'],
    ['augusta.ada.king.countess.of.lovelace@example.com', 'augustaadakingcounte'],
  ])('derives a handle from %s', (email, expected) => {
    expect(handleFromEmail(email)).toBe(expected)
  })
})

describe('ClaimHandle', () => {
  beforeEach(() => {
    dryRunMock.mockReset()
    claimHandleMock.mockReset()
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
    dryRunMock.mockResolvedValue(AVAILABLE)
    renderClaim()

    expect(screen.getByText(/It's permanent\./)).toBeInTheDocument()
    expect(screen.getByText(/It's public\./)).toBeInTheDocument()
    expect(screen.getByText(/address of every app/)).toBeInTheDocument()
  })

  it('prefills from the email local part', () => {
    dryRunMock.mockResolvedValue(AVAILABLE)
    renderClaim()

    expect(screen.getByLabelText('Your handle')).toHaveValue('adalovelace')
  })

  it('shows an unavailable prefill as refused, choosing no substitute', async () => {
    dryRunMock.mockRejectedValue(new ApiError('taken', 409, 'handle_taken'))
    renderClaim()

    await waitFor(() =>
      expect(screen.getByText('Taken. Try adding a word or a number.')).toBeInTheDocument(),
    )
    expect(screen.getByLabelText('Your handle')).toHaveValue('adalovelace')
    expect(screen.getByRole('button', { name: 'Claim this name' })).toBeDisabled()
  })

  it('checks availability with a dry-run claim that stores nothing', async () => {
    dryRunMock.mockResolvedValue(AVAILABLE)
    renderClaim()

    await waitFor(() => expect(dryRunMock).toHaveBeenCalledWith('adalovelace'))
    expect(claimHandleMock).not.toHaveBeenCalled()
  })

  it('claims only through a confirmation showing the frozen suffix, and no app label', async () => {
    dryRunMock.mockResolvedValue(AVAILABLE)
    claimHandleMock.mockResolvedValue(AVAILABLE)
    renderClaim()

    const claim = await screen.findByRole('button', { name: 'Claim this name' })
    await waitFor(() => expect(claim).toBeEnabled())
    fireEvent.click(claim)

    expect(screen.getByText('-adalovelace.freepod.app')).toBeInTheDocument()
    expect(screen.queryByText('your app')).not.toBeInTheDocument()
    expect(claimHandleMock).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Yes, claim it' }))
    await waitFor(() => expect(claimHandleMock).toHaveBeenCalledWith('adalovelace'))
  })

  it('does not demand the name be retyped', async () => {
    dryRunMock.mockResolvedValue(AVAILABLE)
    renderClaim()

    const claim = await screen.findByRole('button', { name: 'Claim this name' })
    await waitFor(() => expect(claim).toBeEnabled())
    fireEvent.click(claim)

    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('goes back with the typed handle intact', async () => {
    dryRunMock.mockResolvedValue(AVAILABLE)
    renderClaim()

    const input = screen.getByLabelText('Your handle')
    fireEvent.change(input, { target: { value: 'grace' } })
    const claim = screen.getByRole('button', { name: 'Claim this name' })
    await waitFor(() => expect(claim).toBeEnabled())
    fireEvent.click(claim)

    fireEvent.click(screen.getByRole('button', { name: 'Go back' }))

    expect(screen.getByLabelText('Your handle')).toHaveValue('grace')
  })

  it('stays put when the claim loses a race', async () => {
    dryRunMock.mockResolvedValue(AVAILABLE)
    claimHandleMock.mockRejectedValue(new ApiError('taken', 409, 'handle_taken'))
    const props = renderClaim()

    const claim = await screen.findByRole('button', { name: 'Claim this name' })
    await waitFor(() => expect(claim).toBeEnabled())
    fireEvent.click(claim)
    fireEvent.click(screen.getByRole('button', { name: 'Yes, claim it' }))

    await waitFor(() =>
      expect(screen.getAllByText('Taken. Try adding a word or a number.').length).toBeGreaterThan(0),
    )
    expect(props.onDismiss).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Your handle')).toHaveValue('adalovelace')
  })
})

describe('ClaimHandle, by context', () => {
  beforeEach(() => {
    dryRunMock.mockReset()
    dryRunMock.mockResolvedValue(AVAILABLE)
  })

  it('shows no application label when choosing the account address', () => {
    renderClaim({ context: 'account' })

    expect(screen.queryByText('your app')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '↻ again' })).not.toBeInTheDocument()
    expect(screen.getByText('.freepod.app')).toBeInTheDocument()
  })

  it('is ready to type into on the dashboard', () => {
    renderClaim({ context: 'account', autoSelect: true })

    const input = screen.getByLabelText('Your handle') as HTMLInputElement
    expect(input).toHaveFocus()
    expect(input.selectionEnd).toBe(input.value.length)
  })

  it('shows the whole deployment hostname on the deploy path', () => {
    renderClaim({ context: 'deploy' })

    expect(screen.getAllByText('your app').length).toBeGreaterThan(0)
  })

  it('asks a different question in each context', () => {
    const { unmount } = render(
      wrap(<ClaimHandle domain="freepod.app" email="a@b.com" onDismiss={vi.fn()} context="account" />),
    )
    expect(screen.getByText(/Nobody else can use it/)).toBeInTheDocument()
    unmount()

    renderClaim({ context: 'deploy' })
    expect(
      screen.getByText(
        'Your app gets a hostname ending in this handle.',
      ),
    ).toBeInTheDocument()
  })
})
