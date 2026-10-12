import type { ProductSummary } from '../landing/useLandingProducts'

/**
 * The deep link for a product's page. Products without a catalog slug fall
 * back to a slugified name.
 */
export function appHref(product: Pick<ProductSummary, 'slug' | 'name'>): string {
  const slug = product.slug ?? product.name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-')
  return `/apps/${slug}`
}
