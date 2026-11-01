import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { getStoredAuthHeaders, useAuthHeaders } from './useAuthEmail'

const KEY = 'caelus.auth.headers'

afterEach(() => window.localStorage.clear())

describe('useAuthHeaders', () => {
  it('sends a subject derived from the email', () => {
    const { result } = renderHook(() => useAuthHeaders())

    act(() => result.current.setEmail('Alice@Example.com'))

    expect(getStoredAuthHeaders()).toEqual({
      'X-Auth-Request-Email': 'Alice@Example.com',
      'X-Auth-Request-User': 'dev:alice@example.com',
    })
  })

  it('gives an address the same subject every time it is entered', () => {
    const { result } = renderHook(() => useAuthHeaders())

    act(() => result.current.setEmail('alice@example.com'))
    const first = getStoredAuthHeaders()['X-Auth-Request-User']
    act(() => result.current.setEmail(''))
    expect(getStoredAuthHeaders()).toEqual({})
    act(() => result.current.setEmail('alice@example.com'))

    expect(getStoredAuthHeaders()['X-Auth-Request-User']).toBe(first)
  })

  it('adds the subject to headers stored before it existed', () => {
    window.localStorage.setItem(KEY, JSON.stringify({ 'X-Auth-Request-Email': 'bob@example.com' }))

    expect(getStoredAuthHeaders()).toEqual({
      'X-Auth-Request-Email': 'bob@example.com',
      'X-Auth-Request-User': 'dev:bob@example.com',
    })
  })
})
