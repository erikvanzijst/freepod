import { useEffect, useState } from 'react'

const HEADERS_KEY = 'caelus.auth.headers'
const SUBJECT_KEY = 'caelus.auth.subject'

export type AuthHeaders = Record<string, string>

export function clearStoredAuthHeaders(): void {
  if (typeof window !== 'undefined') {
    window.localStorage.removeItem(HEADERS_KEY)
    window.localStorage.removeItem(SUBJECT_KEY)
  }
}

export function getStoredAuthHeaders(): AuthHeaders {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(HEADERS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
      return parsed as AuthHeaders
    }
  } catch {
    // corrupted value — ignore
  }
  return {}
}

function getEmailFromHeaders(headers: AuthHeaders): string {
  return headers['X-Auth-Request-Email'] ?? ''
}

// The dev session's Keycloak subject: generated once and held across email
// changes, so a dev session resolves to one stable record the way a real
// identity does (the subject is the join key; the email is mutable).
function getOrCreateSubject(): string {
  if (typeof window === 'undefined') return ''
  const existing = window.localStorage.getItem(SUBJECT_KEY)
  if (existing) return existing
  const subject = crypto.randomUUID()
  window.localStorage.setItem(SUBJECT_KEY, subject)
  return subject
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
      setHeaders({
        'X-Auth-Request-Email': newEmail,
        'X-Auth-Request-User': getOrCreateSubject(),
      })
    } else {
      setHeaders({})
    }
  }

  return { headers, setHeaders, email, setEmail }
}
