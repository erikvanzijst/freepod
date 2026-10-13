import { useQuery } from '@tanstack/react-query'
import { Box, Divider, Typography } from '@mui/material'
import { ApiError } from '../api/client'
import { getDeploymentSftp } from '../api/endpoints'
import { SftpCredentialsFields } from './SftpCredentialsFields'

/**
 * React Query hook for a deployment's SFTP credentials. A 404 means "this
 * product exposes no files" — a normal state, not an error — so it is never
 * retried, and callers can treat `data` presence as "SFTP is available".
 */
export function useSftpCredentials(userId: number, deploymentId: string, enabled = true) {
  return useQuery({
    enabled,
    queryKey: ['deployment-sftp', userId, deploymentId],
    queryFn: () => getDeploymentSftp(userId, deploymentId),
    retry: (_count, err) => !(err instanceof ApiError && err.status === 404),
  })
}

interface SftpAccessPanelProps {
  userId: number
  deploymentId: string
}

/**
 * Inline read-only SFTP access details (used in the admin deployment dialog).
 * Renders nothing when the product exposes no files (404), so it can be dropped
 * into a view unconditionally.
 */
export function SftpAccessPanel({ userId, deploymentId }: SftpAccessPanelProps) {
  const { data: creds, error } = useSftpCredentials(userId, deploymentId)

  if (error || !creds) return null

  return (
    <Box>
      <Divider sx={{ my: 2 }} />
      <Typography variant="subtitle2" gutterBottom>
        File access (SFTP)
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Browse and download your app's files with any SFTP client. Access is
        read-only.
      </Typography>
      <SftpCredentialsFields creds={creds} />
    </Box>
  )
}
