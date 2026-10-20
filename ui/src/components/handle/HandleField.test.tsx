import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { HandleField } from './HandleField'

const claimHandleMock = vi.fn()

vi.mock('../../api/endpoints', () => ({
  claimHandle: (...args: unknown[]) => claimHandleMock(...args),
}))

function matchMedia(reduced: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: reduced && query.includes('reduce'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
}

const available = { handle: 'ada', suffix: '-ada.freepod.app', domain: 'freepod.app' }

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('HandleField', () => {
  beforeEach(() => {
    claimHandleMock.mockReset()
    matchMedia(false)
  })

  it('shows the whole address, with only the handle editable', () => {
    render(<HandleField value="ada" onChange={vi.fn()} domain="freepod.app" />)

    expect(screen.getByLabelText('Your handle')).toHaveValue('ada')
    expect(screen.getByText('-')).toBeInTheDocument()
    expect(screen.getByText('.freepod.app')).toBeInTheDocument()
    // The reel's home slot, and no second input beside it.
    expect(screen.getAllByText('your app').length).toBeGreaterThan(0)
    expect(screen.getAllByRole('textbox')).toHaveLength(1)
  })

  it('shows no application label where there is no application', () => {
    render(<HandleField value="ada" onChange={vi.fn()} domain="freepod.app" showReel={false} />)

    expect(screen.queryByText('your app')).not.toBeInTheDocument()
    expect(screen.queryByText('-')).not.toBeInTheDocument()
  })

  it('checks the handle with a dry-run claim, debounced', async () => {
    claimHandleMock.mockResolvedValue(available)
    render(<HandleField value="Ada" onChange={vi.fn()} domain="freepod.app" />)

    expect(screen.getByText('Checking…')).toBeInTheDocument()
    await waitFor(() =>
      expect(claimHandleMock).toHaveBeenCalledWith('ada', expect.objectContaining({ dryRun: true })),
    )
    await waitFor(() =>
      expect(screen.getByText("Available — this one's yours if you want it.")).toBeInTheDocument(),
    )
  })

  it.each([
    ['handle_invalid', 400, 'Letters and digits only, 2 to 20 characters.'],
    ['handle_reserved', 400, 'Freepod uses this one itself.'],
    ['handle_taken', 409, 'Taken. Try adding a word or a number.'],
  ])('names the cause of a %s refusal', async (code, status, message) => {
    claimHandleMock.mockRejectedValue(new ApiError('refused', status, code))
    render(<HandleField value="x" onChange={vi.fn()} domain="freepod.app" />)

    await waitFor(() => expect(screen.getByText(message)).toBeInTheDocument())
  })

  it('explains that a dash is not allowed', async () => {
    claimHandleMock.mockRejectedValue(new ApiError('refused', 400, 'handle_invalid'))
    const onChange = vi.fn()
    const { rerender } = render(<HandleField value="" onChange={onChange} domain="freepod.app" />)

    fireEvent.change(screen.getByLabelText('Your handle'), { target: { value: 'ada-lovelace' } })
    expect(onChange).toHaveBeenCalledWith('ada-lovelace')
    rerender(<HandleField value="ada-lovelace" onChange={onChange} domain="freepod.app" />)

    await waitFor(() =>
      expect(screen.getByText('Letters and digits only, 2 to 20 characters.')).toBeInTheDocument(),
    )
  })

  it('reports its status to the parent so the claim action can follow it', async () => {
    claimHandleMock.mockRejectedValue(new ApiError('taken', 409, 'handle_taken'))
    const onStatusChange = vi.fn()
    render(
      <HandleField value="ada" onChange={vi.fn()} domain="freepod.app" onStatusChange={onStatusChange} />,
    )

    expect(onStatusChange).toHaveBeenCalledWith({ status: 'checking' })
    await waitFor(() =>
      expect(onStatusChange).toHaveBeenCalledWith({ status: 'refused', reason: 'handle_taken' }),
    )
  })

  it('reports an empty handle without asking the platform', async () => {
    const onStatusChange = vi.fn()
    render(<HandleField value="" onChange={vi.fn()} domain="freepod.app" onStatusChange={onStatusChange} />)

    expect(screen.getByText('Pick a name to continue.')).toBeInTheDocument()
    expect(claimHandleMock).not.toHaveBeenCalled()
    expect(onStatusChange).toHaveBeenCalledWith({ status: 'empty' })
  })

  it('offers a replay control, and hides it under reduced motion', () => {
    const { unmount } = render(<HandleField value="ada" onChange={vi.fn()} domain="freepod.app" />)
    expect(screen.getByRole('button', { name: '↻ again' })).toBeInTheDocument()
    unmount()

    matchMedia(true)
    render(<HandleField value="ada" onChange={vi.fn()} domain="freepod.app" />)
    expect(screen.queryByRole('button', { name: '↻ again' })).not.toBeInTheDocument()
  })

  it('selects the prefill so typing replaces it', () => {
    render(<HandleField value="adalovelace" onChange={vi.fn()} domain="freepod.app" autoSelect />)

    const input = screen.getByLabelText('Your handle') as HTMLInputElement
    expect(input).toHaveFocus()
    expect(input.selectionStart).toBe(0)
    expect(input.selectionEnd).toBe('adalovelace'.length)
  })
})
