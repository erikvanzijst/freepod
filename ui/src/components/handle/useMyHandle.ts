import { useQuery } from '@tanstack/react-query'
import { getMyHandle } from '../../api/endpoints'
import { useAuth } from '../../state/AuthContext'

/** The handle this account holds, its hostname suffix, and the tenant domain either way. */
export function useMyHandle() {
  const { user } = useAuth()
  return useQuery({
    queryKey: ['my-handle'],
    queryFn: getMyHandle,
    enabled: Boolean(user),
  })
}
