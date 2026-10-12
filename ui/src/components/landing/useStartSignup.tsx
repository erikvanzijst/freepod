import { useCallback, useState } from 'react'
import { useAuth } from '../../state/AuthContext'

/** True when running behind Keycloak/oauth2-proxy (auth handled by proxy). */
const proxyAuth = Boolean(import.meta.env.VITE_KEYCLOAK_ACCOUNT_URL)

/**
 * Drives the landing page's primary call-to-action.
 *
 * - In production (behind oauth2-proxy/Keycloak): kick off the hosted
 *   sign-in/registration flow, returning to `path` (the root by default).
 * - In local dev (no proxy): open the email dialog so the SPA can attach an
 *   identity to requests; the caller navigates to `returnTo` once it is saved.
 */
export function useStartSignup() {
  const { setEmail } = useAuth()
  const [dialogOpen, setDialogOpen] = useState(false)
  // Where to land once signed in; the root unless a page asked for more.
  const [returnTo, setReturnTo] = useState('/')

  // Often wired straight to onClick, so a click event may arrive as `path`.
  const start = useCallback((path?: unknown) => {
    const target = typeof path === 'string' ? path : '/'
    if (proxyAuth) {
      const rd = encodeURIComponent(window.location.origin + target)
      // oauth2-proxy initiates the Keycloak login/registration flow here.
      window.location.href = `/oauth2/start?rd=${rd}`
    } else {
      setReturnTo(target)
      setDialogOpen(true)
    }
  }, [])

  return { start, dialogOpen, setDialogOpen, setEmail, returnTo }
}

export default useStartSignup
