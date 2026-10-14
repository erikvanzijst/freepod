import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { listProducts } from '../../api/endpoints'
import { useAuth } from '../../state/AuthContext'
import { installSearch, useInstallRequest } from '../useInstallRequest'

/**
 * Install on an app page: opens the install flow over the page, after sign-up
 * when the visitor is anonymous. `flow` is the product and plan to show it for,
 * once the user's deployable products have loaded.
 */
export function useAppInstall(productId: number | undefined, startSignup: (path: string) => void) {
  const { user } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const request = useInstallRequest()
  const products = useQuery({ queryKey: ['products'], queryFn: () => listProducts(), enabled: Boolean(user) })

  const product =
    user && request.requested ? products.data?.find((p) => p.id === productId && p.template_id) : undefined

  const install = (plan?: string) => {
    if (user) request.request(plan)
    else startSignup(location.pathname + installSearch(plan))
  }

  return {
    install,
    flow: product ? { product, plan: request.plan } : null,
    /** The plan named in the URL, to preselect on the page. */
    plan: request.plan,
    close: request.clear,
    launched: () => navigate('/'),
  }
}
