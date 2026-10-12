import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/** The query that asks a page to open its install flow, e.g. after sign-up. */
export function installSearch(planId?: number): string {
  const params = new URLSearchParams({ install: '1' })
  if (planId !== undefined) params.set('plan', String(planId))
  return `?${params}`
}

/**
 * An install requested on the current page through `?install=1&plan=<id>`,
 * kept in the URL so it survives the sign-up round trip. `request` opens it in
 * place and `clear` drops it.
 */
export function useInstallRequest() {
  const [params, setParams] = useSearchParams()
  const plan = Number(params.get('plan'))

  const update = useCallback(
    (planId: number | undefined, open: boolean) =>
      setParams(
        (current) => {
          const next = new URLSearchParams(current)
          next.delete('install')
          next.delete('plan')
          if (open) new URLSearchParams(installSearch(planId)).forEach((value, key) => next.set(key, value))
          return next
        },
        { replace: true },
      ),
    [setParams],
  )
  const request = useCallback((planId?: number) => update(planId, true), [update])
  const clear = useCallback(() => update(undefined, false), [update])

  return {
    requested: params.has('install'),
    planId: Number.isInteger(plan) && plan > 0 ? plan : undefined,
    request,
    clear,
  }
}
