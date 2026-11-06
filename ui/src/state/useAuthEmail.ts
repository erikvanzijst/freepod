import { useEffect, useState } from 'react'

const HEADERS_KEY = 'caelus.auth.headers'

export type AuthHeaders = Record<string, string>

export function clearStoredAuthHeaders(): void {
  if (typeof window !== 'undefined') {
    window.localStorage.removeItem(HEADERS_KEY)
  }
}

// Local development stands in for the edge with the email alone. Without a
// subject the API resolves the caller by email and binds nothing, which also
// reaches an account already bound to its real Keycloak subject, as on the dev
// database.
function identityHeaders(email: string): AuthHeaders {
  return { 'X-Auth-Request-Email': email }
}

export function getStoredAuthHeaders(): AuthHeaders {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(HEADERS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
      // Only the email is kept, so a subject stored by an earlier version is dropped.
      const email = (parsed as AuthHeaders)['X-Auth-Request-Email']
      return email ? identityHeaders(email) : {}
    }
  } catch {
    // corrupted value — ignore
  }
  return {}
}

function getEmailFromHeaders(headers: AuthHeaders): string {
  return headers['X-Auth-Request-Email'] ?? ''
}

export function useAuthHeaders() {
  const [headers, setHeaders] = useState<AuthHeaders>(getStoredAuthHeaders)

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (Object.keys(headers).length > 0) {
      window.localStorage.setItem(HEADERS_KEY, JSON.stringify(headers))
    } else {
      window.localStorage.removeItem(HEADERS_KEY)
    }
  }, [headers])

  const email = getEmailFromHeaders(headers)

  const setEmail = (newEmail: string) => {
    if (newEmail) {
      setHeaders(identityHeaders(newEmail))
    } else {
      setHeaders({})
    }
  }

  return { headers, setHeaders, email, setEmail }
}
