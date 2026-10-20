import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { HandlePanel } from './HandlePanel'

const handleQuery = vi.hoisted(() => ({
  value: { isLoading: false, data: undefined as unknown },
}))

vi.mock('./useMyHandle', () => ({ useMyHandle: () => handleQuery.value }))

describe('HandlePanel', () => {
  it('shows the held handle and its suffix as a fact, with no way to change it', () => {
    handleQuery.value = {
      isLoading: false,
      data: { handle: 'alice', suffix: '-alice.freepod.app', domain: 'freepod.app' },
    }
    render(<HandlePanel />)

    expect(screen.getByText('alice')).toBeInTheDocument()
    expect(screen.getByText('<app>-alice.freepod.app')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /change|edit/i })).not.toBeInTheDocument()
  })

  it('says where the choice is made when none is held', () => {
    handleQuery.value = {
      isLoading: false,
      data: { handle: null, suffix: null, domain: 'freepod.app' },
    }
    render(<HandlePanel />)

    expect(screen.getByText(/haven't chosen a handle yet/)).toBeInTheDocument()
  })
})
