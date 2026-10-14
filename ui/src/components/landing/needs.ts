import { compareCategories } from './landingTokens'
import type { ProductSummary } from './useLandingProducts'

export interface Need {
  category: string
  apps: ProductSummary[]
  /** The first app's tagline: the description is the app page's long Markdown text. */
  blurb?: string
  /** Every service the category's apps are an alternative to, once each. */
  alternatives: string[]
}

/** The storefront's apps grouped by category, most familiar uses first. */
export function groupByNeed(products: ProductSummary[]): Need[] {
  const groups = new Map<string, ProductSummary[]>()
  for (const p of products) {
    const category = p.category?.trim()
    if (!category) continue
    groups.set(category, [...(groups.get(category) ?? []), p])
  }
  return [...groups.entries()]
    .sort(([a], [b]) => compareCategories(a, b))
    .map(([category, apps]) => ({
      category,
      apps,
      blurb: apps.find((a) => a.tagline)?.tagline ?? undefined,
      alternatives: [
        ...new Set(apps.flatMap((a) => (a.replaces ?? '').split('·').map((s) => s.trim()).filter(Boolean))),
      ],
    }))
}

export const orList = (names: string[]) =>
  names.length <= 1 ? names.join('') : `${names.slice(0, -1).join(', ')} or ${names[names.length - 1]}`
