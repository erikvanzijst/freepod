import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { addDeploymentAccess, getDeploymentAccess, removeDeploymentAccess } from '../../api/endpoints'

/** A deployment's access list, and the owner's two changes to it. */
export function useAccessList(userId: number, deploymentId: string, enabled = true) {
  const queryClient = useQueryClient()
  const queryKey = ['deployment-access', userId, deploymentId]
  const query = useQuery({ enabled, queryKey, queryFn: () => getDeploymentAccess(userId, deploymentId) })
  // The dashboard row counts the list, so it is stale after either change.
  const settled = () => {
    queryClient.invalidateQueries({ queryKey })
    queryClient.invalidateQueries({ queryKey: ['deployments'] })
  }
  const add = useMutation({
    mutationFn: (email: string) => addDeploymentAccess(userId, deploymentId, email),
    onSuccess: settled,
  })
  const remove = useMutation({
    mutationFn: (entryId: string) => removeDeploymentAccess(userId, deploymentId, entryId),
    onSuccess: settled,
  })
  return { query, add, remove }
}
