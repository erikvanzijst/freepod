import { useQuery } from '@tanstack/react-query'
import { Box, Divider, Typography } from '@mui/material'
import { ApiError } from '../api/client'
import { getDeploymentDatabase } from '../api/endpoints'
import { DatabaseFields } from './DatabaseFields'

/**
 * React Query hook for a deployment's database details. A 404 means "this
 * deployment has no database" — a normal state, not an error — so it is never
 * retried, and callers can treat `data` presence as "there is a database".
 *
 * That 404 also covers the interval before a deployment's first reconcile has
 * provisioned one, which is exactly an interval in which the deployment is not
 * settled. Callers re-request when it settles rather than showing a
 * database-specific "being prepared" state, which would duplicate the
 * deployment's own status in a second place that could disagree with it.
 */
export function useDatabaseDetails(userId: number, deploymentId: string, enabled = true) {
  return useQuery({
    enabled,
    queryKey: ['deployment-database', userId, deploymentId],
    queryFn: () => getDeploymentDatabase(userId, deploymentId),
    retry: (_count, err) => !(err instanceof ApiError && err.status === 404),
  })
}

interface DatabasePanelProps {
  userId: number
  deploymentId: string
}

/**
 * Inline read-only database details (used in the admin deployment dialog).
 * Renders nothing when the deployment has no database (404), so it can be
 * dropped into a view unconditionally — the same shape as SftpAccessPanel.
 */
export function DatabasePanel({ userId, deploymentId }: DatabasePanelProps) {
  const { data: database, error } = useDatabaseDetails(userId, deploymentId)

  if (error || !database) return null

  return (
    <Box>
      <Divider sx={{ my: 2 }} />
      <Typography variant="subtitle2" gutterBottom>
        Database (PostgreSQL)
      </Typography>
      <DatabaseFields database={database} />
    </Box>
  )
}
