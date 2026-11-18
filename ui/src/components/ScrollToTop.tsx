import { useEffect, useRef } from 'react'
import { useLocation, useNavigationType } from 'react-router-dom'

/** How long to wait for a fragment's target to render before giving up. */
const FRAGMENT_WAIT_MS = 10000

/**
 * Scrolls to the element a `#fragment` names as soon as it exists. The page
 * renders only after the session check, long after the browser looked for the
 * target itself. Once web fonts finish loading the layout can shift, so the
 * target is lined up again unless the visitor has scrolled meanwhile.
 */
function scrollToFragment(hash: string): () => void {
  const id = decodeURIComponent(hash.slice(1))
  let cancelled = false

  const scroll = (target: HTMLElement) => {
    target.scrollIntoView()
    const settled = window.scrollY
    void document.fonts?.ready.then(() => {
      if (!cancelled && Math.abs(window.scrollY - settled) < 2) target.scrollIntoView()
    })
  }

  const found = document.getElementById(id)
  if (found) {
    scroll(found)
    return () => {
      cancelled = true
    }
  }

  const observer = new MutationObserver(() => {
    const target = document.getElementById(id)
    if (!target) return
    stop()
    scroll(target)
  })
  const timer = setTimeout(() => stop(), FRAGMENT_WAIT_MS)
  const stop = () => {
    observer.disconnect()
    clearTimeout(timer)
  }
  observer.observe(document.body, { childList: true, subtree: true })

  return () => {
    cancelled = true
    stop()
  }
}

/**
 * Client-side navigation keeps the window's scroll offset, so a page reached
 * from far down another one would open partway down. Reset to the top on every
 * new route, or scroll to its `#fragment` target. A page opened with a
 * fragment also scrolls to it. Back/forward (POP) is left alone so the browser
 * can restore the previous position. A change to the query string alone
 * (filters, an expanded row) is not a new route and keeps the position.
 */
export function ScrollToTop() {
  const { pathname, hash } = useLocation()
  const navigationType = useNavigationType()
  const route = pathname + hash
  const previous = useRef(route)
  const initialHash = useRef(hash)

  useEffect(() => {
    if (initialHash.current) return scrollToFragment(initialHash.current)
  }, [])

  useEffect(() => {
    if (previous.current === route) return
    previous.current = route
    if (navigationType === 'POP') return
    if (hash) return scrollToFragment(hash)
    window.scrollTo(0, 0)
  }, [route, hash, navigationType])

  return null
}

export default ScrollToTop
