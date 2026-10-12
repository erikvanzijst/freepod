/**
 * The shape of an app page: the product and its plans, its store listing
 * (`GET /products/{id}/listing`) and its releases, all from the API.
 */

export interface Screenshot {
  /** Shown in the page's strip; small, so pages load fast. */
  thumbnailUrl: string
  /** Full size, fetched only once the viewer opens. */
  url: string
  caption: string
  /** Mobile shots are portrait and laid out narrower than desktop ones. */
  form: 'desktop' | 'mobile'
  /** Attribution the image's license requires, e.g. "Nextcloud GmbH · CC BY-SA 4.0". */
  credit?: { text: string; href?: string | null } | null
}

export interface ListingLink {
  label: string
  href: string
  kind: 'website' | 'docs' | 'source' | 'releases' | 'ios' | 'android'
}

export interface ListingPlan {
  id: number
  name: string
  priceCents: number
  /** Markdown; its first line doubles as the plan's one-line summary. */
  description: string
}

export interface ListingFeature {
  title: string
  body: string
  /** Key into a small fixed icon set, so catalog data stays plain strings. */
  icon: string
}

export interface Release {
  version: string
  /** When Freepod first shipped this version; null for versions older than tracking. */
  availableAt: string | null
  /** Markdown. */
  notes: string
}

export interface AppListing {
  id: number
  slug: string
  name: string
  tagline: string
  /** Markdown. */
  description: string
  category: string
  replaces: string[]
  iconUrl: string | null
  version: string
  /** When Freepod first shipped the current version: the oldest template row carrying it. */
  updatedAt: string
  license: string
  screenshots: Screenshot[]
  features: ListingFeature[]
  /** Newest first. */
  releases: Release[]
  links: ListingLink[]
  plans: ListingPlan[]
}

/** Cheapest paid plan, the "from" price shown beside the install button. */
export function fromPriceCents(listing: AppListing): number {
  const paid = listing.plans.map((p) => p.priceCents).filter((c) => c > 0)
  return paid.length ? Math.min(...paid) : 0
}

/** The plan preselected on the page: the cheapest paid one, else the first. */
export function defaultPlanIndex(listing: AppListing): number {
  const from = fromPriceCents(listing)
  return Math.max(0, listing.plans.findIndex((p) => p.priceCents === from))
}
