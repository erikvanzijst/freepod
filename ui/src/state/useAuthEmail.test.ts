import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { clearStoredAuthHeaders, useAuthHeaders } from './useAuthEmail'

describe('useAuthHeaders', () => {
  afterEach(() => {
    window.localStorage.clear()
  })

  it('sends a subject alongside the email', () => {
    const { result } = renderHook(() => useAuthHeaders())
    act(() => {
      result.current.setEmail('a@x.com')
    })
    expect(result.current.headers['X-Auth-Request-Email']).toBe('a@x.com')
    expect(result.current.headers['X-Auth-Request-User']).toBeTruthy()
  })

  it('keeps the same subject across an email change', () => {
    const { result } = renderHook(() => useAuthHeaders())
    act(() => {
      result.current.setEmail('a@x.com')
    })
    const subject = result.current.headers['X-Auth-Request-User']
    act(() => {
      result.current.setEmail('b@x.com')
    })
    expect(result.current.headers['X-Auth-Request-Email']).toBe('b@x.com')
    expect(result.current.headers['X-Auth-Request-User']).toBe(subject)
  })

  it('clears the subject when the session is cleared', () => {
    const { result } = renderHook(() => useAuthHeaders())
    act(() => {
      result.current.setEmail('a@x.com')
    })
    act(() => {
      clearStoredAuthHeaders()
    })
    expect(window.localStorage.getItem('caelus.auth.subject')).toBeNull()
  })
})
