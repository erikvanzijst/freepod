import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SubdomainField } from './SubdomainField'

const checkHostnameMock = vi.fn()

vi.mock('../../api/endpoints', () => ({
  checkHostname: (...args: unknown[]) => checkHostnameMock(...args),
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

describe('SubdomainField', () => {
  beforeEach(() => {
    checkHostnameMock.mockReset()
    matchMedia(false)
  })

  it('shows the whole address, with only the label editable', () => {
    render(<SubdomainField value="ada" onChange={vi.fn()} domain="freepod.eu" />)

    expect(screen.getByLabelText('Your domain name')).toHaveValue('ada')
    expect(screen.getByText('.freepod.eu')).toBeInTheDocument()
    // The reel's home slot, and no second input beside it.
    expect(screen.getAllByText('your app').length).toBeGreaterThan(0)
    expect(screen.getAllByRole('textbox')).toHaveLength(1)
  })

  it('checks the label under the platform domain, debounced', async () => {
    checkHostnameMock.mockResolvedValue({ fqdn: 'ada.freepod.eu', usable: true, reason: null })
    render(<SubdomainField value="ada" onChange={vi.fn()} domain="freepod.eu" />)

    expect(screen.getByText('Checking…')).toBeInTheDocument()
    await waitFor(() => expect(checkHostnameMock).toHaveBeenCalledWith('ada.freepod.eu'))
    await waitFor(() =>
      expect(screen.getByText("Available — this one's yours if you want it.")).toBeInTheDocument(),
    )
  })

  it.each([
    ['invalid', 'Letters, numbers and hyphens only, 2 to 63 characters.'],
    ['reserved', 'Freepod uses this one itself.'],
    ['claimed', 'Taken. Try adding a word or a number.'],
  ])('names the cause of a %s refusal', async (reason, message) => {
    checkHostnameMock.mockResolvedValue({ fqdn: 'x.freepod.eu', usable: false, reason })
    render(<SubdomainField value="x" onChange={vi.fn()} domain="freepod.eu" />)

    await waitFor(() => expect(screen.getByText(message)).toBeInTheDocument())
  })

  it('reports its status to the parent so the claim action can follow it', async () => {
    checkHostnameMock.mockResolvedValue({ fqdn: 'ada.freepod.eu', usable: false, reason: 'claimed' })
    const onStatusChange = vi.fn()
    render(
      <SubdomainField value="ada" onChange={vi.fn()} domain="freepod.eu" onStatusChange={onStatusChange} />,
    )

    await waitFor(() =>
      expect(onStatusChange).toHaveBeenCalledWith({ status: 'refused', reason: 'claimed' }),
    )
  })

  it('reports an empty label without asking the platform', async () => {
    const onStatusChange = vi.fn()
    render(<SubdomainField value="" onChange={vi.fn()} domain="freepod.eu" onStatusChange={onStatusChange} />)

    expect(screen.getByText('Pick a name to continue.')).toBeInTheDocument()
    expect(checkHostnameMock).not.toHaveBeenCalled()
    expect(onStatusChange).toHaveBeenCalledWith({ status: 'empty' })
  })

  it('strips dots, because a label is one level', () => {
    const onChange = vi.fn()
    render(<SubdomainField value="" onChange={onChange} domain="freepod.eu" />)

    fireEvent.change(screen.getByLabelText('Your domain name'), { target: { value: 'ada.love' } })

    expect(onChange).toHaveBeenCalledWith('adalove')
  })

  it('offers a replay control, and hides it under reduced motion', () => {
    const { unmount } = render(<SubdomainField value="ada" onChange={vi.fn()} domain="freepod.eu" />)
    expect(screen.getByRole('button', { name: '↻ again' })).toBeInTheDocument()
    unmount()

    matchMedia(true)
    render(<SubdomainField value="ada" onChange={vi.fn()} domain="freepod.eu" />)
    expect(screen.queryByRole('button', { name: '↻ again' })).not.toBeInTheDocument()
  })

  it('selects the prefill so typing replaces it', () => {
    render(<SubdomainField value="adalovelace" onChange={vi.fn()} domain="freepod.eu" autoSelect />)

    const input = screen.getByLabelText('Your domain name') as HTMLInputElement
    expect(input).toHaveFocus()
    expect(input.selectionStart).toBe(0)
    expect(input.selectionEnd).toBe('adalovelace'.length)
  })
})
