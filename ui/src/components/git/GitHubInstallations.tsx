import { Alert, Box, Button, Chip, CircularProgress, Divider, Stack, Typography } from '@mui/material'
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded'
import type { GitHubInstallation } from '../../api/types'
import { fg } from '../landing/landingTokens'

interface GitHubInstallationsProps {
  installations: GitHubInstallation[] | undefined
  loading: boolean
  failed: boolean
}

function InstallationRow({ item }: { item: GitHubInstallation }) {
  return (
    <Stack direction="row" alignItems="center" spacing={1.5} sx={{ py: 1.5 }}>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography noWrap sx={{ fontWeight: 600 }}>
          {item.account}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {item.account_type === 'Organization' ? 'Organization' : 'Personal account'}
        </Typography>
      </Box>
      <Chip
        size="small"
        variant="outlined"
        label={item.repository_selection === 'all' ? 'All repositories' : 'Selected repositories'}
        sx={{ height: 22, fontSize: 11.5, color: fg.muted, flexShrink: 0 }}
      />
      <Button
        size="small"
        href={item.html_url}
        target="_blank"
        rel="noopener noreferrer"
        endIcon={<OpenInNewRoundedIcon fontSize="small" />}
        sx={{ flexShrink: 0 }}
      >
        Configure
      </Button>
    </Stack>
  )
}

/** The GitHub accounts the Freepod app is installed on, as the connected user sees them. */
export function GitHubInstallations({ installations, loading, failed }: GitHubInstallationsProps) {
  if (loading) {
    return (
      <Stack alignItems="center" sx={{ py: 3 }}>
        <CircularProgress size={20} />
      </Stack>
    )
  }
  if (failed) {
    return (
      <Alert severity="error" variant="outlined">
        Could not load the accounts the Freepod app is installed on.
      </Alert>
    )
  }
  if (!installations?.length) {
    return (
      <Typography color="text.secondary" variant="body2" sx={{ py: 1.5 }}>
        The Freepod app is not installed on any GitHub account yet. Install it to choose which
        repositories Freepod can reach.
      </Typography>
    )
  }
  return (
    <Box>
      {installations.map((item, index) => (
        <Box key={item.id}>
          {index > 0 && <Divider />}
          <InstallationRow item={item} />
        </Box>
      ))}
    </Box>
  )
}
