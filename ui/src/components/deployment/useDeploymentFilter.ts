import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { Deployment } from '../../api/types'
import { matchesQuery } from '../../utils/search'
import { useListedProducts } from '../landing/useLandingProducts'
import { catalogSearchFields } from '../appsgallery/useGallery'

export const sortOptions = [
  { key: 'newest', label: 'Newest first' },
  { key: 'oldest', label: 'Oldest first' },
  { key: 'name', label: 'Name' },
  { key: 'updated', label: 'Recently updated' },
] as const

export type SortKey = (typeof sortOptions)[number]['key']

const time = (iso?: string | null) => (iso ? new Date(iso).getTime() : 0)
const appName = (d: Deployment) => d.desired_template?.product?.name ?? ''

const comparators: Record<SortKey, (a: Deployment, b: Deployment) => number> = {
  newest: (a, b) => time(b.created_at) - time(a.created_at),
  oldest: (a, b) => time(a.created_at) - time(b.created_at),
  name: (a, b) => appName(a).localeCompare(appName(b)) || (a.hostname ?? '').localeCompare(b.hostname ?? ''),
  updated: (a, b) => time(b.last_reconcile_at) - time(a.last_reconcile_at),
}

/**
 * Search and sort for the user's deployments, kept in the URL as `search` and
 * `sort` (apart from the catalog panel's `q`). A search looks in the same
 * fields as the catalog's, plus the deployment's address and plan.
 */
export function useDeploymentFilter(deployments: Deployment[]) {
  const [params, setParams] = useSearchParams()
  const search = params.get('search') ?? ''
  const sort = (sortOptions.find((o) => o.key === params.get('sort'))?.key ?? 'newest') as SortKey
  const products = useListedProducts()

  const set = (key: 'search' | 'sort', value: string) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        if (value) next.set(key, value)
        else next.delete(key)
        return next
      },
      { replace: true },
    )

  const results = useMemo(() => {
    const byId = new Map((products.data ?? []).map((p) => [p.id, p]))
    return deployments
      .filter((d) => {
        const product = d.desired_template?.product
        const listed = product ? byId.get(product.id) : undefined
        const fields = listed ? catalogSearchFields(listed) : [product?.name, product?.tagline]
        return matchesQuery([...fields, d.hostname, d.subscription?.plan_template?.plan?.name], search)
      })
      .sort(comparators[sort])
  }, [deployments, products.data, search, sort])

  return { search, sort, results, setSearch: (v: string) => set('search', v), setSort: (v: SortKey) => set('sort', v === 'newest' ? '' : v) }
}
