import { formatEuro } from '../landing/usePricing'
import type { AppListing, ListingPlan } from './listing'

export function formatReleaseDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

/** Key/value facts about the listing: version, update date, license, hosting. */
export function listingFacts(listing: AppListing): { label: string; value: string }[] {
  const facts = [
    { label: 'Version', value: listing.version },
    { label: 'Updated', value: listing.updatedAt && formatReleaseDate(listing.updatedAt) },
    { label: 'License', value: listing.license },
    { label: 'Category', value: listing.category },
    { label: 'Hosted in', value: 'European Union' },
  ]
  return facts.filter((fact) => fact.value)
}

export function planPrice(plan: ListingPlan): string {
  return plan.priceCents === 0 ? 'Free' : formatEuro(plan.priceCents)
}

/**
 * A plan's one-line summary: the first line of its markdown description,
 * with list markers and inline emphasis stripped.
 */
export function planSummary(plan: ListingPlan): string {
  const first = plan.description.split('\n').find((line) => line.trim()) ?? ''
  return first
    .replace(/^\s*(?:[-*+]|\d+\.)\s+/, '')
    .replace(/(\*\*|__|\*|_|`)/g, '')
    .trim()
}
