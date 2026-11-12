import type { Deployment, DeploymentStatus } from '../api/types'

export function statusColor(
  status?: DeploymentStatus,
): 'default' | 'info' | 'warning' | 'success' | 'error' {
  switch (status) {
    case 'ready':
      return 'success'
    case 'error':
      return 'error'
    case 'pending':
      return 'info'
    case 'provisioning':
    case 'deleting':
      return 'warning'
    case 'deleted':
      return 'default'
    default:
      return 'info'
  }
}

export function isTransitionalStatus(status?: DeploymentStatus) {
  return status === 'pending' || status === 'provisioning' || status === 'deleting'
}

export function underMaintenance(d: Deployment): boolean {
  return d.power?.desired === 'stopped' && d.power.reason === 'maintenance'
}

/** How often to refresh a deployment listing: while anything is in transition,
 * a stop or start still being applied included, more slowly while anything is
 * under maintenance, and otherwise not at all. */
export function listingRefetchInterval(deployments: Deployment[]): number | false {
  const changing = deployments.some(
    (d) => isTransitionalStatus(d.status) || (d.power !== undefined && d.power.desired !== d.power.applied),
  )
  if (changing) return 3000
  return deployments.some(underMaintenance) ? 10000 : false
}
