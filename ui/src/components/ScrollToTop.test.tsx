import { act, render, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useNavigate, type NavigateFunction } from 'react-router-dom'
import ScrollToTop from './ScrollToTop'

function setup(initial = '/apps') {
  const ref: { navigate?: NavigateFunction } = {}
  function Capture() {
    const navigate = useNavigate()
    useEffect(() => {
      ref.navigate = navigate
    }, [navigate])
    return null
  }
  render(
    <MemoryRouter initialEntries={[initial]}>
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

function addSection(id: string) {
  const section = document.createElement('section')
  section.id = id
  document.body.appendChild(section)
  return section
}

describe('ScrollToTop', () => {
  const scrollTo = vi.fn()
  const scrollIntoView = vi.fn()

  beforeEach(() => {
    scrollTo.mockReset()
    scrollIntoView.mockReset()
    window.scrollTo = scrollTo as unknown as typeof window.scrollTo
    Element.prototype.scrollIntoView = scrollIntoView
    document.querySelectorAll('section').forEach((section) => section.remove())
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

  it('scrolls to the fragment target of a new route', () => {
    const section = addSection('pricing')
    const go = setup()
    go('/dev#pricing')
    expect(scrollTo).not.toHaveBeenCalled()
    expect(scrollIntoView.mock.contexts).toEqual([section])
  })

  it('scrolls to the fragment of the opening URL once its target renders', async () => {
    setup('/dev#pricing')
    expect(scrollIntoView).not.toHaveBeenCalled()
    const section = addSection('pricing')
    await waitFor(() => expect(scrollIntoView.mock.contexts).toContain(section))
  })

  it('leaves back/forward alone', () => {
    const go = setup()
    go('/dev')
    scrollTo.mockReset()
    go(-1)
    expect(scrollTo).not.toHaveBeenCalled()
    expect(scrollIntoView).not.toHaveBeenCalled()
  })
})
