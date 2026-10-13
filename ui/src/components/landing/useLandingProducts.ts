import { useQuery } from '@tanstack/react-query'
import { listProducts } from '../../api/endpoints'
import type { ProductVisibility } from '../../api/types'
import { useAuth } from '../../state/AuthContext'

export interface ProductSummary {
  id: number
  name: string
  slug?: string | null
  tagline?: string | null
  description?: string | null
  iconUrl?: string | null
  category?: string | null
  replaces?: string | null
  visibility: ProductVisibility
}

/** Fetch every product the API lists to the caller, preserving API order. */
export async function loadListedProducts(): Promise<ProductSummary[]> {
  const products = await listProducts()
  return products.map((product) => ({
    id: product.id,
    name: product.name,
    slug: product.slug,
    tagline: product.tagline,
    description: product.description,
    iconUrl: product.icon_url,
    category: product.category,
    replaces: product.replaces,
    visibility: product.visibility,
  }))
}

/** Fetch the storefront's products (`public` only), preserving API order. */
export async function loadVisibleProducts(): Promise<ProductSummary[]> {
  return (await loadListedProducts()).filter((product) => product.visibility === 'public')
}

/** Cached query of the products shown across the landing page. */
export function useLandingProducts() {
  return useQuery({
    queryKey: ['landing-products'],
    queryFn: loadVisibleProducts,
    staleTime: 5 * 60 * 1000,
  })
}

/**
 * Every product the API lists to the current user: `unlisted` ones too, and
 * `admin` ones for administrators. Reachable by link, not shown in the storefront.
 */
export function useListedProducts() {
  const { user } = useAuth()
  return useQuery({
    queryKey: ['listed-products', user?.id ?? null],
    queryFn: loadListedProducts,
    staleTime: 5 * 60 * 1000,
  })
}

export default useLandingProducts
