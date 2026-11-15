import { renderHook } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { Deployment } from '../../api/types'
import { useDeploymentFilter } from './useDeploymentFilter'

vi.mock('../landing/useLandingProducts', () => ({ useListedProducts: () => ({ data: [] }) }))

const custom = { id: 3, product: { id: 9, name: 'Custom user app', slug: 'custom' } } as Deployment['desired_template']

function deployment(id: string, name: string, hostname: string): Deployment {
  return {
    id,
    name,
    hostname,
    desired_template_id: 3,
    desired_template: custom,
    user_id: 1,
    user: { id: 1, email: 'o@example.com', is_admin: false, created_at: '' },
    created_at: '2026-08-01T00:00:00Z',
    namespace: 'ns',
    power: { desired: 'running', applied: 'running' },
  }
}

const deployments = [
  deployment('1', 'Recipes', 'recipes.example.test'),
  deployment('2', 'Arkanoid', 'zz.example.test'),
  deployment('3', 'Pong', 'pong.example.test'),
]

function filter(query: string) {
  const { result } = renderHook(() => useDeploymentFilter(deployments), {
    wrapper: ({ children }) => <MemoryRouter initialEntries={[`/?${query}`]}>{children}</MemoryRouter>,
  })
  return result.current.results.map((d) => d.name)
}

describe('useDeploymentFilter', () => {
  it('finds a deployment by its name', () => {
    expect(filter('search=ark')).toEqual(['Arkanoid'])
  })

  it('sorts by deployment name', () => {
    expect(filter('sort=name')).toEqual(['Arkanoid', 'Pong', 'Recipes'])
  })
})
