import { useQuery } from '@tanstack/react-query'
import { getMySubdomain } from '../../api/endpoints'
import { useAuth } from '../../state/AuthContext'

/** The domain name this account holds, and the platform domain either way. */
export function useMySubdomain() {
  const { user } = useAuth()
  return useQuery({
    queryKey: ['my-subdomain'],
    queryFn: getMySubdomain,
    enabled: Boolean(user),
  })
}
