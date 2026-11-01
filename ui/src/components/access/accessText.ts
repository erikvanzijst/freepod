import { ApiError } from '../../api/client'
import type { AccessEntry } from '../../api/types'

export function shortDay(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function initials(name: string | null | undefined, email: string): string {
  const words = (name ?? '').trim().split(/\s+/).filter(Boolean)
  if (words.length >= 2) return (words[0][0] + words[words.length - 1][0]).toUpperCase()
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return email.slice(0, 2).toUpperCase()
}

/** The reason an addition was refused, in words for the field beside it. */
export function addError(err: unknown, email: string, ownerEmail: string, limit: number): string {
  const typed = email.trim().toLowerCase()
  if (!(err instanceof ApiError)) return 'Something went wrong. Please try again.'
  switch (err.code) {
    case 'access_invalid_email':
      return 'Enter a full email address, like name@example.com.'
    case 'access_duplicate':
      return typed === ownerEmail.toLowerCase() ? 'That is you. You always have access.' : `${typed} is already on the list.`
    case 'access_list_full':
      return `The list is full: it holds ${limit} people. Remove someone to add another.`
    default:
      return err.message
  }
}

export type AccessFilter = 'all' | 'signed-in' | 'not-yet'

export function filterEntries(entries: AccessEntry[], search: string, filter: AccessFilter): AccessEntry[] {
  const q = search.trim().toLowerCase()
  return entries.filter(
    (e) =>
      (filter === 'all' || (filter === 'signed-in') === Boolean(e.bound_at)) &&
      (!q || e.email.includes(q) || (e.name ?? '').toLowerCase().includes(q)),
  )
}
