import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { User } from '../../api/types'
import { FeedbackDialog } from './FeedbackDialog'
import type { FeedbackSession } from './FeedbackProvider'
import { record, reset } from './diagnostics'

const submitFeedback = vi.fn()
vi.mock('../../api/endpoints', () => ({ submitFeedback: (...a: unknown[]) => submitFeedback(...a) }))

const start = vi.fn()
vi.mock('../landing/useStartSignup', () => ({
  default: () => ({ start, dialogOpen: false, setDialogOpen: vi.fn(), setEmail: vi.fn(), returnTo: '/' }),
}))

let currentUser: User | null = { id: 7, email: 'ana@example.com', is_admin: false } as User
vi.mock('../../state/AuthContext', () => ({
  useAuth: () => ({ user: currentUser, loading: false, email: '', setEmail: vi.fn() }),
}))

const shot = new Blob(['jpeg'], { type: 'image/jpeg' })

function open(session: Partial<FeedbackSession> = {}, onClose = vi.fn(), path = '/settings/handle') {
  const full: FeedbackSession = { page: '/settings/handle', screenshot: Promise.resolve(shot), fromLink: false, ...session }
  render(
    <MemoryRouter initialEntries={[path]}>
      <FeedbackDialog session={full} onClose={onClose} />
    </MemoryRouter>,
  )
  return onClose
}

function write(text: string) {
  fireEvent.change(screen.getByLabelText('Your message'), { target: { value: text } })
}

beforeEach(() => {
  currentUser = { id: 7, email: 'ana@example.com', is_admin: false } as User
  URL.createObjectURL = vi.fn(() => 'blob:shot')
  URL.revokeObjectURL = vi.fn()
  submitFeedback.mockResolvedValue({ id: 1 })
})

afterEach(() => {
  submitFeedback.mockReset()
  start.mockReset()
  reset()
  vi.useRealTimers()
})

describe('FeedbackDialog', () => {
  it('offers three topics, none chosen, and keeps Send disabled without one', async () => {
    open()
    const topics = screen.getAllByRole('radio')
    expect(topics.map((t) => t.textContent)).toEqual(['Something is wrong', 'An idea', 'Something else'])
    expect(topics.every((t) => t.getAttribute('aria-checked') === 'false')).toBe(true)
    write('The button is gone')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    fireEvent.click(screen.getByRole('radio', { name: 'An idea' }))
    write('   ')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    await screen.findByRole('button', { name: 'Enlarge screenshot' })
  })

  it('sends with the screenshot, page and diagnostics, thanks, and closes on its own', async () => {
    record({ kind: 'api', method: 'GET', path: '/api/me', status: 500 })
    const onClose = open()
    await screen.findByRole('button', { name: 'Enlarge screenshot' })
    vi.useFakeTimers({ shouldAdvanceTime: true })
    fireEvent.click(screen.getByRole('radio', { name: 'Something is wrong' }))
    write('The deploy button does nothing')
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('Thank you')
    const sent = submitFeedback.mock.calls[0][0]
    expect(sent).toMatchObject({ topic: 'bug', message: 'The deploy button does nothing', page: '/settings/handle', uiBuild: 'dev', screenshot: shot })
    expect(sent.diagnostics).toEqual([expect.objectContaining({ kind: 'api', path: '/api/me', status: 500 })])
    expect(sent.viewport).toMatch(/^\d+x\d+$/)
    await act(() => vi.advanceTimersByTimeAsync(2500))
    expect(onClose).toHaveBeenCalled()
  })

  it('sends no screenshot once it is removed', async () => {
    open()
    fireEvent.click(await screen.findByRole('button', { name: 'Remove screenshot' }))
    expect(screen.queryByRole('button', { name: 'Enlarge screenshot' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: 'An idea' }))
    write('Region picker')
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('Thank you')
    expect(submitFeedback.mock.calls[0][0].screenshot).toBeNull()
  })

  it('opens without a thumbnail when capture fails, and still sends', async () => {
    open({ screenshot: Promise.resolve(null) })
    await waitFor(() => expect(screen.queryByLabelText('Taking a screenshot')).not.toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Enlarge screenshot' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: 'Something else' }))
    write('Hi')
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('Thank you')
    expect(submitFeedback.mock.calls[0][0].screenshot).toBeNull()
  })

  it('waits for a pending capture before sending', async () => {
    let finish: (b: Blob | null) => void = () => {}
    open({ screenshot: new Promise((resolve) => (finish = resolve)) })
    expect(screen.getByLabelText('Taking a screenshot')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: 'Something else' }))
    write('Quick one')
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(submitFeedback).not.toHaveBeenCalled()
    await act(async () => finish(shot))
    await screen.findByText('Thank you')
    expect(submitFeedback.mock.calls[0][0].screenshot).toBe(shot)
  })

  it('keeps the message and shows when feedback can be sent again', async () => {
    submitFeedback.mockRejectedValue(
      new ApiError('You have sent feedback 20 times in the past 24 hours. You can send more after 2026-11-27 10:00 UTC.', 429, 'feedback_limit'),
    )
    open()
    fireEvent.click(screen.getByRole('radio', { name: 'An idea' }))
    write('One more thing')
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText(/You can send more after 2026-11-27 10:00 UTC/)).toBeInTheDocument()
    expect(screen.getByLabelText('Your message')).toHaveValue('One more thing')
    expect(screen.getByRole('radio', { name: 'An idea' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('button', { name: 'Enlarge screenshot' })).toBeInTheDocument()
  })

  it('states what is sent along', async () => {
    open()
    await screen.findByRole('button', { name: 'Enlarge screenshot' })
    expect(screen.getByText(/Sent with your account, this page’s address, the screenshot and technical details/)).toBeInTheDocument()
  })

  it('asks a visitor to sign in or email, with no form', () => {
    currentUser = null
    open({ page: '/apps', screenshot: Promise.resolve(shot) }, vi.fn(), '/apps')
    expect(screen.queryByLabelText('Your message')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'feedback@freepod.eu' })).toHaveAttribute('href', 'mailto:feedback@freepod.eu')
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(start).toHaveBeenCalledWith('/apps?feedback=1&from=%2Fapps')
  })
})
