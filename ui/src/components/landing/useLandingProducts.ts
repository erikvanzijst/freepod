import { useQuery } from '@tanstack/react-query'
import { listProducts } from '../../api/endpoints'

export interface ProductSummary {
  id: number
  name: string
  slug?: string | null
  tagline?: string | null
  description?: string | null
  iconUrl?: string | null
  category?: string | null
  replaces?: string | null
}

/** Fetch the storefront's products (`public` only), preserving API order. */
export async function loadVisibleProducts(): Promise<ProductSummary[]> {
  const products = await listProducts()
  return products
    .filter((product) => product.visibility === 'public')
    .map((product) => ({
      id: product.id,
      name: product.name,
      slug: product.slug,
      tagline: product.tagline,
      description: product.description,
      iconUrl: product.icon_url,
      category: product.category,
      replaces: product.replaces,
    }))
}

/** Cached query of the products shown across the landing page. */
export function useLandingProducts() {
  return useQuery({
    queryKey: ['landing-products'],
    queryFn: loadVisibleProducts,
    staleTime: 5 * 60 * 1000,
  })
}

export default useLandingProducts
