import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ClaimSubdomainBanner } from './ClaimSubdomainBanner'

describe('ClaimSubdomainBanner', () => {
  it('keeps the claim reachable after it is dismissed', () => {
    const onChoose = vi.fn()
    render(<ClaimSubdomainBanner onChoose={onChoose} />)

    fireEvent.click(screen.getByRole('button', { name: 'Claim your free domain name' }))

    expect(onChoose).toHaveBeenCalled()
  })

  it('records nothing', () => {
    const before = { ...localStorage }
    render(<ClaimSubdomainBanner onChoose={vi.fn()} />)

    expect({ ...localStorage }).toEqual(before)
  })
})
