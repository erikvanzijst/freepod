import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Product, ProductVisibility } from '../../api/types'
import { loadVisibleProducts } from './useLandingProducts'

const listProductsMock = vi.fn()

vi.mock('../../api/endpoints', () => ({
  listProducts: () => listProductsMock(),
}))

function product(id: number, name: string, visibility: ProductVisibility): Product {
  return {
    id,
    name,
    description: `${name} blurb`,
    icon_url: null,
    category: 'Photos & video',
    replaces: null,
    visibility,
    curated: false,
    created_at: '2026-01-01T00:00:00Z',
  }
}

describe('loadVisibleProducts', () => {
  beforeEach(() => listProductsMock.mockReset())

  it('keeps only public products, in API order', async () => {
    listProductsMock.mockResolvedValue([
      product(1, 'Immich', 'public'),
      product(2, 'Custom user app', 'unlisted'),
      product(3, 'Staging', 'admin'),
      product(4, 'Vaultwarden', 'public'),
    ])

    const visible = await loadVisibleProducts()

    expect(visible.map((p) => p.name)).toEqual(['Immich', 'Vaultwarden'])
  })

  it('decides by visibility, not by name', async () => {
    listProductsMock.mockResolvedValue([
      product(1, 'Hello World', 'public'),
      product(2, 'Photos', 'unlisted'),
    ])

    const visible = await loadVisibleProducts()

    expect(visible.map((p) => p.name)).toEqual(['Hello World'])
  })

  it('maps the listing to the storefront summary', async () => {
    listProductsMock.mockResolvedValue([product(1, 'Immich', 'public')])

    expect(await loadVisibleProducts()).toEqual([
      {
        id: 1,
        name: 'Immich',
        description: 'Immich blurb',
        iconUrl: null,
        category: 'Photos & video',
        replaces: null,
      },
    ])
  })
})
