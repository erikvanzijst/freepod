import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ClaimHandleBanner } from './ClaimHandleBanner'

describe('ClaimHandleBanner', () => {
  it('keeps the claim reachable after it is dismissed', () => {
    const onChoose = vi.fn()
    render(<ClaimHandleBanner onChoose={onChoose} />)

    fireEvent.click(screen.getByRole('button', { name: 'Choose your handle' }))

    expect(onChoose).toHaveBeenCalled()
  })

  it('records nothing', () => {
    const before = { ...localStorage }
    render(<ClaimHandleBanner onChoose={vi.fn()} />)

    expect({ ...localStorage }).toEqual(before)
  })
})
