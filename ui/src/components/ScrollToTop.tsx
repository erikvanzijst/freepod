import { useEffect, useRef } from 'react'
import { useLocation, useNavigationType } from 'react-router-dom'

/**
 * Client-side navigation keeps the window's scroll offset, so a page reached
 * from far down another one would open partway down. Reset to the top on every
 * new route. Back/forward (POP) is left alone so the browser can restore the
 * previous position, and a `#fragment` is left for the target section. A
 * change to the query string alone (filters, an expanded row) is not a new
 * route and keeps the position.
 */
export function ScrollToTop() {
  const { pathname, hash } = useLocation()
  const navigationType = useNavigationType()
  const route = pathname + hash
  const previous = useRef(route)

  useEffect(() => {
    if (previous.current === route) return
    previous.current = route
    if (navigationType !== 'POP' && !hash) window.scrollTo(0, 0)
  }, [route, hash, navigationType])

  return null
}

export default ScrollToTop
