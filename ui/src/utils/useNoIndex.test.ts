import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useNoIndex } from './useNoIndex'

const robots = () => document.head.querySelector('meta[name="robots"]')?.getAttribute('content')

describe('useNoIndex', () => {
  it('adds a noindex tag while active and removes it after', () => {
    const { rerender, unmount } = renderHook(({ active }) => useNoIndex(active), { initialProps: { active: false } })
    expect(robots()).toBeUndefined()

    rerender({ active: true })
    expect(robots()).toBe('noindex')

    rerender({ active: false })
    expect(robots()).toBeUndefined()

    rerender({ active: true })
    unmount()
    expect(robots()).toBeUndefined()
  })
})
