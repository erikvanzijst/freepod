import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { getProductListing, listDeployments, listPlans, listProducts } from '../../api/endpoints'
import { resolveApiPath } from '../../api/client'
import { useAuth } from '../../state/AuthContext'
import { useLandingProducts, useListedProducts, type ProductSummary } from '../landing/useLandingProducts'
import { usePricing } from '../landing/usePricing'
import { installSearch, useInstallRequest } from '../useInstallRequest'
import { appHref } from '../apppage/appHref'
import { matchesQuery } from '../../utils/search'
import type { Screenshot } from '../apppage/listing'

export interface GalleryApp extends ProductSummary {
  href: string
  /** Cheapest paid monthly price in cents; null when only free plans exist, undefined while loading. */
  fromCents: number | null | undefined
  running: number
}

/** The fields a catalog search looks in; the dashboard searches the same ones. */
export function catalogSearchFields(app: Pick<ProductSummary, 'name' | 'tagline' | 'category' | 'replaces' | 'description'>) {
  return [app.name, app.tagline, app.category, app.replaces, app.description]
}

/** The gallery's apps, filters (kept in the URL) and the signed-in user's running counts. */
export function useGallery() {
  const { user } = useAuth()
  const storefront = useLandingProducts()
  const listed = useListedProducts()
  // Administrators also see unlisted and admin-only products, badged as such.
  const products = user?.is_admin ? listed : storefront
  const pricing = usePricing()
  const deployments = useQuery({
    queryKey: ['deployments', user?.id],
    queryFn: () => listDeployments(user!.id),
    enabled: Boolean(user?.id),
  })
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const category = params.get('category') ?? ''

  const setFilter = (key: 'q' | 'category', value: string) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        if (value) next.set(key, value)
        else next.delete(key)
        return next
      },
      { replace: true },
    )

  const clearFilters = () =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        next.delete('q')
        next.delete('category')
        return next
      },
      { replace: true },
    )

  const apps = useMemo<GalleryApp[]>(() => {
    const prices = new Map((pricing.data ?? []).map((p) => [p.id, p.isFallback ? null : p.fromCents]))
    const running = new Map<number, number>()
    for (const d of deployments.data ?? []) {
      const id = d.desired_template?.product_id
      if (id !== undefined) running.set(id, (running.get(id) ?? 0) + 1)
    }
    // Public apps first; for administrators, unlisted and admin-only ones follow.
    const ordered = [...(products.data ?? [])].sort((a, b) => Number(a.visibility !== 'public') - Number(b.visibility !== 'public'))
    return ordered.map((p) => ({
      ...p,
      iconUrl: p.iconUrl ? resolveApiPath(p.iconUrl) : null,
      href: appHref(p),
      fromCents: pricing.data && prices.has(p.id) ? (prices.get(p.id) ?? null) : undefined,
      running: running.get(p.id) ?? 0,
    }))
  }, [products.data, pricing.data, deployments.data])

  const categories = useMemo(() => {
    const counts = new Map<string, number>()
    for (const app of apps) if (app.category) counts.set(app.category, (counts.get(app.category) ?? 0) + 1)
    return [...counts.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => a.name.localeCompare(b.name))
  }, [apps])

  const results = apps.filter((app) => (!category || app.category === category) && matchesQuery(catalogSearchFields(app), q))

  return { apps, results, categories, q, category, setFilter, clearFilters, loading: products.isLoading, signedIn: Boolean(user) }
}

/** The listing content a preview shows: screenshots, features and plans. */
export function usePreview(productId: number | null) {
  const enabled = productId !== null
  const listing = useQuery({
    queryKey: ['product-listing', productId],
    queryFn: () => getProductListing(productId!),
    enabled,
    staleTime: 5 * 60 * 1000,
  })
  const plans = useQuery({
    queryKey: ['plans', productId],
    queryFn: () => listPlans(productId!),
    enabled,
    staleTime: 5 * 60 * 1000,
  })
  return {
    screenshots: (listing.data?.screenshots ?? []).map<Screenshot>((s) => ({
      thumbnailUrl: resolveApiPath(s.thumbnail_url),
      url: resolveApiPath(s.url),
      caption: s.caption,
      form: s.form,
      credit: s.credit,
    })),
    features: listing.data?.features ?? [],
    plans: (plans.data ?? [])
      .filter((p) => p.template)
      .map((p) => ({ id: p.id, name: p.name, priceCents: p.template!.price_cents })),
    loading: listing.isLoading,
  }
}

/**
 * Install from the gallery. Signed in, it opens the install flow in place;
 * anonymous, it signs up and lands on the app's own page with the flow open.
 */
export function useGalleryInstall(startSignup: (path: string) => void) {
  const { user } = useAuth()
  const request = useInstallRequest()
  const [productId, setProductId] = useState<number | null>(null)
  const products = useQuery({ queryKey: ['products'], queryFn: () => listProducts(), enabled: Boolean(user) })
  const product =
    user && request.requested && productId !== null
      ? products.data?.find((p) => p.id === productId && p.template_id)
      : undefined

  const install = (app: GalleryApp, planId?: number) => {
    if (user) {
      setProductId(app.id)
      request.request(planId)
    } else {
      startSignup(app.href + installSearch(planId))
    }
  }

  return { install, flow: product ? { product, planId: request.planId } : null, close: request.clear }
}
