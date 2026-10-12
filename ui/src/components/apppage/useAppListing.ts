import { useQuery } from '@tanstack/react-query'
import { resolveApiPath } from '../../api/client'
import { getProductListing, listPlans, listReleases } from '../../api/endpoints'
import { useLandingProducts } from '../landing/useLandingProducts'
import { appHref } from './appHref'
import type { AppListing } from './listing'

const STALE = 5 * 60 * 1000

/**
 * The listing for `/apps/:slug`, assembled from the product, its plans, its
 * store listing and its releases. `listing` is null while products load or
 * when no storefront product has this slug.
 */
export function useAppListing(slug: string | undefined) {
  const products = useLandingProducts()
  const product = products.data?.find((p) => appHref(p) === `/apps/${slug}`)
  const enabled = product !== undefined

  const plans = useQuery({ queryKey: ['plans', product?.id], queryFn: () => listPlans(product!.id), enabled, staleTime: STALE })
  const content = useQuery({
    queryKey: ['product-listing', product?.id],
    queryFn: () => getProductListing(product!.id),
    enabled,
    staleTime: STALE,
  })
  const releases = useQuery({
    queryKey: ['product-releases', product?.id],
    queryFn: () => listReleases(product!.id),
    enabled,
    staleTime: STALE,
  })

  if (!product) return { listing: null, loading: products.isLoading }

  const listing: AppListing = {
    id: product.id,
    slug: slug ?? '',
    name: product.name,
    tagline: product.tagline ?? '',
    description: product.description ?? '',
    category: product.category ?? '',
    replaces: product.replaces?.split('·').map((s) => s.trim()).filter(Boolean) ?? [],
    iconUrl: product.iconUrl ? resolveApiPath(product.iconUrl) : null,
    version: content.data?.version ?? '',
    updatedAt: content.data?.version_available_at ?? '',
    license: content.data?.license ?? '',
    features: content.data?.features ?? [],
    links: content.data?.links ?? [],
    screenshots: (content.data?.screenshots ?? []).map((shot) => ({
      thumbnailUrl: resolveApiPath(shot.thumbnail_url),
      url: resolveApiPath(shot.url),
      caption: shot.caption,
      form: shot.form,
      credit: shot.credit,
    })),
    releases: (releases.data ?? []).map((r) => ({ version: r.version, notes: r.notes, availableAt: r.available_at ?? null })),
    plans: (plans.data ?? [])
      .filter((p) => p.template)
      .map((p) => ({ id: p.id, name: p.name, priceCents: p.template!.price_cents, description: p.template!.description ?? '' })),
  }
  return { listing, loading: plans.isLoading || content.isLoading || releases.isLoading }
}
