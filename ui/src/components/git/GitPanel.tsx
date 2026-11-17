import { Alert, Card, CircularProgress, Stack, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { listGitConnections } from '../../api/endpoints'
import { useAuth } from '../../state/AuthContext'
import { AppStudioLink } from './AppStudioLink'
import { GitHubSection } from './GitHubSection'
import { GitOutcomeNotice } from './GitOutcomeNotice'

/** The account's connections to git hosts. */
export function GitPanel() {
  const { user } = useAuth()
  const connections = useQuery({
    queryKey: ['git', user?.id, 'connections'],
    queryFn: () => listGitConnections(user!.id),
    enabled: Boolean(user?.id),
  })
  const github = connections.data?.find((c) => c.provider === 'github')
  const [params, setParams] = useSearchParams()
  const autoConnect = params.get('connect') === 'github'
  const clearAutoConnect = () => {
    const next = new URLSearchParams(params)
    next.delete('connect')
    setParams(next, { replace: true })
  }

  return (
    <Card sx={{ p: { xs: 2.5, sm: 3 } }}>
      <Typography variant="h6">Git</Typography>
      <Typography color="text.secondary" variant="body2" sx={{ mt: 0.5, mb: 3 }}>
          Connect your GitHub account to let <AppStudioLink /> safely work with your git repositories.
      </Typography>

      <GitOutcomeNotice />

      {connections.isLoading && (
        <Stack alignItems="center" sx={{ py: 6 }}>
          <CircularProgress size={22} />
        </Stack>
      )}

      {connections.error != null && (
        <Alert severity="error" variant="outlined">
          Could not load your git connections.
        </Alert>
      )}

      {connections.isSuccess && user && (
        <GitHubSection
          userId={user.id}
          connection={github}
          autoConnect={autoConnect}
          onAutoConnect={clearAutoConnect}
        />
      )}
    </Card>
  )
}

export default GitPanel
