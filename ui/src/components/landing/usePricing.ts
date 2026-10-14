import { useQuery } from '@tanstack/react-query'
import { listPlans } from '../../api/endpoints'
import { loadVisibleProducts, type ProductSummary } from './useLandingProducts'

/** Fallback "starting at" price (cents) for products with no paid plan yet. */
const FALLBACK_PRICE_CENTS = 900

export interface ProductPrice extends ProductSummary {
  /** Cheapest non-free monthly price, in cents (or the fallback). */
  fromCents: number
  /** True when no paid plan exists and the fallback price is shown. */
  isFallback: boolean
  /** Whether a free plan exists. */
  hasFree: boolean
}

/** Format a cents amount as a euro string, hiding ".00" for round values. */
export function formatEuro(cents: number): string {
  const euros = cents / 100
  return Number.isInteger(euros) ? `€${euros}` : `€${euros.toFixed(2)}`
}

async function loadPricing(): Promise<ProductPrice[]> {
  const visible = await loadVisibleProducts()

  // Fan out: fetch each product's plans in parallel and pick the cheapest
  // non-free one. A product with only free plans falls back to a placeholder.
  const priced = await Promise.all(
    visible.map(async (product) => {
      let fromCents = FALLBACK_PRICE_CENTS
      let isFallback = true
      let hasFree = false
      try {
        const plans = await listPlans(product.id)
        hasFree = plans.some((plan) => plan.template?.price_cents === 0)
        const paidPrices = plans
          .map((plan) => plan.template?.price_cents ?? 0)
          .filter((cents) => cents > 0)
        if (paidPrices.length > 0) {
          fromCents = Math.min(...paidPrices)
          isFallback = false
        }
      } catch {
        // Keep the fallback price if a product's plans can't be loaded.
      }
      return { ...product, fromCents, isFallback, hasFree }
    }),
  )

  // Cheapest first — leads the pricing section with the lowest entry point.
  return priced.sort((a, b) => a.fromCents - b.fromCents)
}

/** Cached query that powers the landing page's "starting at" pricing cards. */
export function usePricing() {
  return useQuery({
    queryKey: ['landing-pricing'],
    queryFn: loadPricing,
    staleTime: 5 * 60 * 1000,
  })
}

export default usePricing
