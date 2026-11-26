import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FeedbackProvider, type FeedbackSession } from './FeedbackProvider'
import { cleanPage, linkedPage } from './page'

const captureViewport = vi.fn(() => Promise.resolve(null))
vi.mock('./capture', () => ({
  captureViewport: () => captureViewport(),
  FEEDBACK_UI_ATTR: 'data-feedback-ui',
}))

vi.mock('./FeedbackDialog', () => ({
  FeedbackDialog: ({ session, onClose }: { session: FeedbackSession; onClose: () => void }) => (
    <div role="dialog">
      <span>page {session.page}</span>
      <span>{session.screenshot ? 'with screenshot' : 'without screenshot'}</span>
      <button onClick={onClose}>close</button>
    </div>
  ),
}))

function Where() {
  const location = useLocation()
  return <output>{location.pathname + location.search}</output>
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <FeedbackProvider>
        <Where />
      </FeedbackProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  captureViewport.mockClear()
  Object.defineProperty(document, 'referrer', { value: '', configurable: true })
})

describe('FeedbackProvider', () => {
  it.each(['/', '/apps', '/apps/immich', '/dev', '/settings/ssh-keys', '/admin/users'])('shows the tab on %s', (path) => {
    renderAt(path)
    expect(screen.getByRole('button', { name: 'Feedback' })).toBeInTheDocument()
  })

  it('hides the tab on legal documents', () => {
    renderAt('/legal/privacy')
    expect(screen.queryByRole('button', { name: 'Feedback' })).not.toBeInTheDocument()
  })

  it('opens from the tab with a screenshot, naming the current page without secrets', () => {
    renderAt('/settings/git?code=abc&installation_id=7')
    fireEvent.click(screen.getByRole('button', { name: 'Feedback' }))
    expect(captureViewport).toHaveBeenCalledOnce()
    expect(screen.getByText('page /settings/git?installation_id=7')).toBeInTheDocument()
    expect(screen.getByText('with screenshot')).toBeInTheDocument()
  })

  it('opens from the link without a screenshot, naming the given page', () => {
    renderAt('/?feedback=1&from=/apps/immich')
    expect(screen.getByText('page /apps/immich')).toBeInTheDocument()
    expect(screen.getByText('without screenshot')).toBeInTheDocument()
    expect(captureViewport).not.toHaveBeenCalled()
  })

  it('names the documentation page the user came from', () => {
    Object.defineProperty(document, 'referrer', {
      value: `${window.location.origin}/docs/developers/deploying`,
      configurable: true,
    })
    renderAt('/?feedback=1')
    expect(screen.getByText('page /docs/developers/deploying')).toBeInTheDocument()
  })

  it('removes the link parameters on close', () => {
    renderAt('/apps?category=photos&feedback=1&from=/apps')
    fireEvent.click(screen.getByRole('button', { name: 'close' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('/apps?category=photos')
  })
})

describe('linkedPage', () => {
  const origin = 'https://freepod.eu'
  it('prefers from, then a same-origin referrer, then /', () => {
    expect(linkedPage('/apps', `${origin}/docs/x`, origin)).toBe('/apps')
    expect(linkedPage('//evil.example', `${origin}/docs/x?token=1`, origin)).toBe('/docs/x')
    expect(linkedPage(null, 'https://elsewhere.example/page', origin)).toBe('/')
    expect(linkedPage(null, '', origin)).toBe('/')
  })
})

describe('cleanPage', () => {
  it('drops the fragment and secret-looking parameters, keeping the rest in order', () => {
    expect(cleanPage('/apps/immich?tab=plans#pricing')).toBe('/apps/immich?tab=plans')
    expect(cleanPage('/x?state=1&a=1&id_token=2&client_secret=3&b=2')).toBe('/x?a=1&b=2')
  })
})
