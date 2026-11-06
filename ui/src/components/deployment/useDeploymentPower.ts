import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { startDeployment, stopDeployment } from '../../api/endpoints'
import type { Deployment } from '../../api/types'

/** A refused stop or start, in the owner's words. */
export function powerRefusal(error: unknown, action: 'stop' | 'start'): string {
  if (error instanceof ApiError && error.status === 409) {
    if (error.code === 'not_startable') return 'This app was stopped for payment and cannot be started here.'
    if (error.code === 'deployment_not_ready') return `This app can't be ${action === 'stop' ? 'stopped' : 'started'} until its current change finishes.`
    return 'This app is busy with another change. Try again shortly.'
  }
  return `Couldn't ${action} the app. Try again shortly.`
}

/** Stop and start a deployment from its row; the listing follows the change. */
export function useDeploymentPower(userId: number, deployment: Deployment) {
  const queryClient = useQueryClient()
  const onSuccess = (updated: Deployment) => {
    queryClient.setQueryData<Deployment[]>(['deployments', userId], (items) =>
      items?.map((item) => (item.id === updated.id ? updated : item)),
    )
    return queryClient.invalidateQueries({ queryKey: ['deployments'] })
  }
  const stop = useMutation({ mutationFn: () => stopDeployment(userId, deployment.id), onSuccess })
  const start = useMutation({ mutationFn: () => startDeployment(userId, deployment.id), onSuccess })
  const error = stop.error ? powerRefusal(stop.error, 'stop') : start.error ? powerRefusal(start.error, 'start') : null
  return {
    stop: () => {
      start.reset()
      stop.mutate()
    },
    start: () => {
      stop.reset()
      start.mutate()
    },
    pending: stop.isPending || start.isPending,
    error,
  }
}
