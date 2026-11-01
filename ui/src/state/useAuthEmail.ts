import { useEffect, useState } from 'react'

const HEADERS_KEY = 'caelus.auth.headers'

export type AuthHeaders = Record<string, string>

export function clearStoredAuthHeaders(): void {
  if (typeof window !== 'undefined') {
    window.localStorage.removeItem(HEADERS_KEY)
  }
}

// Local development stands in for the edge, which sends the Keycloak subject
// with the email. Deriving it from the email keeps each typed address one
// stable account, as one Keycloak account would be.
export function devSubject(email: string): string {
  return `dev:${email.trim().toLowerCase()}`
}

function identityHeaders(email: string): AuthHeaders {
  return { 'X-Auth-Request-Email': email, 'X-Auth-Request-User': devSubject(email) }
}

export function getStoredAuthHeaders(): AuthHeaders {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(HEADERS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
      const headers = parsed as AuthHeaders
      const email = headers['X-Auth-Request-Email']
      return email && !headers['X-Auth-Request-User'] ? identityHeaders(email) : headers
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
