import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Feedback, FeedbackList } from '../../../api/types'
import { AdminSidebar } from '../../AdminSidebar'
import { FeedbackDetail } from './FeedbackDetail'
import { FeedbackPanel } from './FeedbackPanel'

const listFeedback = vi.fn()
const getFeedback = vi.fn()
const getFeedbackScreenshot = vi.fn()
const setFeedbackResolved = vi.fn()
vi.mock('../../../api/endpoints', () => ({
  listFeedback: (...a: unknown[]) => listFeedback(...a),
  getFeedback: (...a: unknown[]) => getFeedback(...a),
  getFeedbackScreenshot: (...a: unknown[]) => getFeedbackScreenshot(...a),
  setFeedbackResolved: (...a: unknown[]) => setFeedbackResolved(...a),
}))

const item = {
  id: 5,
  created_at: '2026-11-26T10:00:00',
  user_id: 7,
  email: 'ana@example.com',
  topic: 'bug' as const,
  excerpt: 'The deploy button does nothing',
  page: '/settings/handle',
  has_screenshot: true,
  read: false,
  resolved: false,
}

const detail: Feedback = {
  ...item,
  message: 'The deploy button does nothing\nat all',
  user_agent: 'Mozilla/5.0',
  viewport: '1440x900',
  ui_build: '4eaa51e',
  api_build: 'b7d2272',
  diagnostics: [{ at: '2026-11-26T09:59:00Z', kind: 'api', method: 'POST', path: '/api/users/7/deployments', status: 500 }],
  screenshot_width: 1440,
  screenshot_height: 900,
  read_at: '2026-11-26T10:05:00',
  resolved_at: null,
  resolved_by: null,
  resolved_by_email: null,
}

let unread = 0
const list = (items = [item]): FeedbackList => ({ items, total: items.length, unread })

function renderAdmin(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AdminSidebar />
        <Routes>
          <Route path="/admin/feedback" element={<FeedbackPanel />} />
          <Route path="/admin/feedback/:id" element={<FeedbackDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  unread = 0
  listFeedback.mockImplementation(async () => list())
  getFeedbackScreenshot.mockResolvedValue(new Blob(['webp'], { type: 'image/webp' }))
  URL.createObjectURL = vi.fn(() => 'blob:shot')
  URL.revokeObjectURL = vi.fn()
})

afterEach(() => vi.clearAllMocks())

describe('Feedback in the admin sidebar', () => {
  it('shows the unread count', async () => {
    unread = 3
    renderAdmin('/admin/feedback')
    expect(await screen.findByLabelText('3 unread')).toBeInTheDocument()
  })

  it('shows no number when nothing is unread', async () => {
    renderAdmin('/admin/feedback')
    await waitFor(() => expect(listFeedback).toHaveBeenCalledWith({ state: 'all', limit: 0 }))
    expect(screen.queryByLabelText(/unread$/)).not.toBeInTheDocument()
  })
})

describe('FeedbackPanel', () => {
  it('lists open feedback by default, unread marked', async () => {
    renderAdmin('/admin/feedback')
    expect(await screen.findByText('The deploy button does nothing')).toBeInTheDocument()
    expect(listFeedback).toHaveBeenCalledWith(expect.objectContaining({ state: 'open', topic: null, offset: 0 }))
    expect(screen.getAllByLabelText('Unread').length).toBeGreaterThan(0)
    expect(screen.getByLabelText('Has a screenshot')).toBeInTheDocument()
  })

  it('switches to resolved feedback', async () => {
    renderAdmin('/admin/feedback')
    await screen.findByText('The deploy button does nothing')
    fireEvent.click(screen.getByRole('button', { name: 'Resolved' }))
    await waitFor(() =>
      expect(listFeedback).toHaveBeenCalledWith(expect.objectContaining({ state: 'resolved' })),
    )
  })
})

describe('FeedbackDetail', () => {
  it('opening an item marks it read and the badge drops', async () => {
    unread = 1
    getFeedback.mockImplementation(async () => {
      unread = 0
      return detail
    })
    renderAdmin('/admin/feedback/5')
    expect(await screen.findByText(/at all/)).toBeInTheDocument()
    expect(getFeedback).toHaveBeenCalledWith(5)
    await waitFor(() => expect(screen.queryByLabelText('1 unread')).not.toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'ana@example.com' })).toHaveAttribute('href', '/admin/users?q=ana%40example.com')
    expect(screen.getByRole('link', { name: '/settings/handle' })).toHaveAttribute('target', '_blank')
    expect(screen.getByText('4eaa51e')).toBeInTheDocument()
    expect(screen.getByText('b7d2272')).toBeInTheDocument()
    expect(screen.getByText(/POST \/api\/users\/7\/deployments → 500/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Reply' })).toHaveAttribute(
      'href',
      expect.stringMatching(/^mailto:ana@example\.com\?subject=/),
    )
    expect(await screen.findByRole('button', { name: 'Enlarge screenshot' })).toBeInTheDocument()
  })

  it('resolves and reopens', async () => {
    getFeedback.mockResolvedValue(detail)
    setFeedbackResolved.mockImplementation(async (_id: number, resolved: boolean) => ({
      ...detail,
      resolved_at: resolved ? '2026-11-26T11:00:00' : null,
      resolved_by: resolved ? 1 : null,
      resolved_by_email: resolved ? 'erik@example.com' : null,
    }))
    renderAdmin('/admin/feedback/5')
    fireEvent.click(await screen.findByRole('button', { name: 'Mark resolved' }))
    expect(await screen.findByText(/by erik@example\.com/)).toBeInTheDocument()
    expect(setFeedbackResolved).toHaveBeenCalledWith(5, true)
    fireEvent.click(screen.getByRole('button', { name: 'Reopen' }))
    await screen.findByRole('button', { name: 'Mark resolved' })
    expect(setFeedbackResolved).toHaveBeenLastCalledWith(5, false)
    expect(within(document.body).queryByText(/by erik@example\.com/)).not.toBeInTheDocument()
  })
})
