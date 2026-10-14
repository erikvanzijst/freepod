import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/** The query that asks a page to open its install flow, e.g. after sign-up. */
export function installSearch(plan?: string): string {
  const params = new URLSearchParams({ install: '1' })
  if (plan) params.set('plan', plan)
  return `?${params}`
}

/** Finds a plan by name, case-insensitively, as plan names are unique that way. */
export function findPlan<T extends { name: string }>(plans: T[], name: string | undefined): T | undefined {
  const wanted = name?.trim().toLowerCase()
  return wanted ? plans.find((p) => p.name.toLowerCase() === wanted) : undefined
}

/**
 * An install requested on the current page through `?install=1&plan=<name>`,
 * kept in the URL so it survives the sign-up round trip. `request` opens it in
 * place and `clear` drops it. `plan` alone, without `install`, is a deep link
 * that only preselects the plan.
 */
export function useInstallRequest() {
  const [params, setParams] = useSearchParams()
  const plan = params.get('plan') || undefined

  const update = useCallback(
    (plan: string | undefined, open: boolean) =>
      setParams(
        (current) => {
          const next = new URLSearchParams(current)
          next.delete('install')
          next.delete('plan')
          if (open) new URLSearchParams(installSearch(plan)).forEach((value, key) => next.set(key, value))
          return next
        },
        { replace: true },
      ),
    [setParams],
  )
  const request = useCallback((plan?: string) => update(plan, true), [update])
  const clear = useCallback(() => update(undefined, false), [update])

  return {
    requested: params.has('install'),
    plan,
    request,
    clear,
  }
}
