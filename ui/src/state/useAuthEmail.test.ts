import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { getStoredAuthHeaders, useAuthHeaders } from './useAuthEmail'

const KEY = 'caelus.auth.headers'

afterEach(() => window.localStorage.clear())

describe('useAuthHeaders', () => {
  it('sends the email alone, so the API resolves the caller by email', () => {
    const { result } = renderHook(() => useAuthHeaders())

    act(() => result.current.setEmail('Alice@Example.com'))

    expect(getStoredAuthHeaders()).toEqual({ 'X-Auth-Request-Email': 'Alice@Example.com' })
  })

  it('forgets the email when it is cleared', () => {
    const { result } = renderHook(() => useAuthHeaders())

    act(() => result.current.setEmail('alice@example.com'))
    act(() => result.current.setEmail(''))

    expect(getStoredAuthHeaders()).toEqual({})
  })

  it('drops a subject stored by an earlier version', () => {
    window.localStorage.setItem(
      KEY,
      JSON.stringify({ 'X-Auth-Request-Email': 'bob@example.com', 'X-Auth-Request-User': 'dev:bob@example.com' }),
    )

    expect(getStoredAuthHeaders()).toEqual({ 'X-Auth-Request-Email': 'bob@example.com' })
  })
})
