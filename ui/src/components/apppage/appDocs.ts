declare const __APP_DOCS__: string[]

const documented = new Set(__APP_DOCS__)

/** The app's page in the docs site, or null when it has none. */
export function appDocsHref(slug: string): string | null {
  return documented.has(slug) ? `/docs/apps/products/${slug}` : null
}
