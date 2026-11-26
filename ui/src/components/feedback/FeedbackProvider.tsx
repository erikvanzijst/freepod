import { useCallback, useMemo, useState, type PropsWithChildren } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { captureViewport } from './capture'
import { FeedbackDialog } from './FeedbackDialog'
import { FeedbackTab } from './FeedbackTab'
import { cleanPage, linkedPage } from './page'

export interface FeedbackSession {
  page: string
  /** The pending or finished capture; null when the dialog opened without one. */
  screenshot: Promise<Blob | null> | null
  fromLink: boolean
}

/** D9: the one Feedback tab and dialog, for every page but the legal documents. */
export function FeedbackProvider({ children }: PropsWithChildren) {
  const location = useLocation()
  const navigate = useNavigate()
  const [tabSession, setTabSession] = useState<FeedbackSession | null>(null)

  const params = new URLSearchParams(location.search)
  const linked = params.get('feedback') === '1'
  const from = params.get('from')

  // D10: `?feedback=1[&from=]` opens the dialog until closing removes the parameters.
  const linkSession = useMemo<FeedbackSession | null>(
    () =>
      linked
        ? { page: linkedPage(from, document.referrer, window.location.origin), screenshot: null, fromLink: true }
        : null,
    [linked, from],
  )
  const session = tabSession ?? linkSession

  const openFromTab = useCallback(() => {
    setTabSession({
      page: cleanPage(location.pathname + location.search),
      screenshot: captureViewport(),
      fromLink: false,
    })
  }, [location.pathname, location.search])

  const close = useCallback(() => {
    setTabSession(null)
    if (linked) {
      const rest = new URLSearchParams(location.search)
      rest.delete('feedback')
      rest.delete('from')
      const query = rest.toString()
      navigate({ pathname: location.pathname, search: query ? `?${query}` : '' }, { replace: true })
    }
  }, [linked, location.pathname, location.search, navigate])

  const hidden = location.pathname.startsWith('/legal/')

  return (
    <>
      {children}
      {!hidden && <FeedbackTab onClick={openFromTab} />}
      {session && <FeedbackDialog key={session.fromLink ? 'link' : 'tab'} session={session} onClose={close} />}
    </>
  )
}

export default FeedbackProvider
