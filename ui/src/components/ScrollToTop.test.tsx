import { act, render } from '@testing-library/react'
import { useEffect } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useNavigate, type NavigateFunction } from 'react-router-dom'
import ScrollToTop from './ScrollToTop'

function setup() {
  const ref: { navigate?: NavigateFunction } = {}
  function Capture() {
    const navigate = useNavigate()
    useEffect(() => {
      ref.navigate = navigate
    }, [navigate])
    return null
  }
  render(
    <MemoryRouter initialEntries={['/apps']}>
      <ScrollToTop />
      <Capture />
    </MemoryRouter>,
  )
  return (to: string | number, replace = false) =>
    act(() => {
      if (typeof to === 'number') ref.navigate!(to)
      else ref.navigate!(to, { replace })
    })
}

describe('ScrollToTop', () => {
  const scrollTo = vi.fn()

  beforeEach(() => {
    scrollTo.mockReset()
    window.scrollTo = scrollTo as unknown as typeof window.scrollTo
  })

  it('scrolls to the top on a new pathname', () => {
    const go = setup()
    go('/dev')
    expect(scrollTo).toHaveBeenCalledWith(0, 0)
  })

  it('keeps the position when only the query string changes', () => {
    const go = setup()
    go('/apps?open=nextcloud', true)
    go('/apps?open=immich', true)
    expect(scrollTo).not.toHaveBeenCalled()
  })

  it('leaves back/forward and fragments alone', () => {
    const go = setup()
    go('/#pricing')
    go(-1)
    expect(scrollTo).not.toHaveBeenCalled()
  })
})
