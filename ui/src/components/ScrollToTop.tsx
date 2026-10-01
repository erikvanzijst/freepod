import { useEffect } from 'react'
import { useLocation, useNavigationType } from 'react-router-dom'

/**
 * Client-side navigation keeps the window's scroll offset, so a page reached
 * from far down another one would open partway down. Reset to the top on every
 * new route. Back/forward (POP) is left alone so the browser can restore the
 * previous position, and a `#fragment` is left for the target section.
 */
export function ScrollToTop() {
  const { pathname, hash } = useLocation()
  const navigationType = useNavigationType()

  useEffect(() => {
    if (navigationType !== 'POP' && !hash) window.scrollTo(0, 0)
  }, [pathname, hash, navigationType])

  return null
}

export default ScrollToTop
