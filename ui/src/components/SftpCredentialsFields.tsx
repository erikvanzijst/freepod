import { Alert, Box, Link, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import type { SftpCredentials } from '../api/types'
import { CopyButton } from './CopyButton'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 96 }}>
        {label}
      </Typography>
      <Typography
        variant="body2"
        data-feedback-redact=""
        sx={{ fontFamily: 'monospace', flex: 1, wordBreak: 'break-all' }}
      >
        {value}
      </Typography>
      <CopyButton value={value} label={label.toLowerCase()} />
    </Box>
  )
}

/**
 * Presentational SFTP connection fields (host/port/username) and how to
 * authenticate. Pure — takes resolved details. Shared by the inline
 * SftpAccessPanel (admin deployment dialog) and the SftpAccessDialog (user
 * dashboard card) so the two surfaces can never drift.
 */
export function SftpCredentialsFields({ creds }: { creds: SftpCredentials }) {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
      {!creds.account_has_ssh_key && (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          Register an SSH key before connecting — without one these details
          cannot be used.{' '}
          <Link component={RouterLink} to="/settings/ssh-keys">
            Add a key
          </Link>
          .
        </Alert>
      )}
      <Row label="Host" value={creds.host} />
      <Row label="Port" value={String(creds.port)} />
      <Row label="Username" value={creds.username} />
      {creds.account_has_ssh_key && (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
          Authenticated with an SSH key registered on your account.{' '}
          <Link component={RouterLink} to="/settings/ssh-keys">
            Manage keys
          </Link>
          .
        </Typography>
      )}
    </Box>
  )
}
