import { useState } from 'react'
import { Alert, Box, IconButton, Tooltip, Typography } from '@mui/material'
import VisibilityIcon from '@mui/icons-material/Visibility'
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff'
import type { DeploymentDatabase } from '../api/types'
import { formatDateTime } from '../utils/format'
import { CopyButton } from './CopyButton'

/** Fixed width, so the mask does not report the password's length. */
const MASK = '•'.repeat(12)

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 4) return `${(bytes / 1024 ** 4).toFixed(1)} TB`
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(0)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

/**
 * How full the database is, as a percentage with the figures behind it.
 *
 * The percentage is the answer to "how much room is left"; the bytes are what
 * makes it checkable. A non-empty database never rounds down to `0%`, which
 * would read as "nothing stored".
 */
function formatUsage(size: number, allowance: number): string {
  const figures = `${formatBytes(size)} of ${formatBytes(allowance)}`
  if (allowance <= 0) return figures
  const percent = (size / allowance) * 100
  const shown = size > 0 && percent < 1 ? '<1' : String(Math.round(percent))
  return `${shown}% (${figures})`
}

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
 * Presentational database details: which database and role the deployment owns,
 * its password, and its usage against its allowance.
 *
 * Deliberately renders **no host, no port and no connection URL**. The address
 * is the in-cluster pooler's and no browser has a route to it, so showing it
 * would offer a connection that cannot be made — and it is also the one part a
 * future forwarded connection replaces. What is here is the part that stays
 * true either way, which is why the panel says where the database is reachable
 * from rather than leaving the omission to read as a gap.
 */
export function DatabaseFields({ database }: { database: DeploymentDatabase }) {
  const [revealed, setRevealed] = useState(false)

  const measured = database.size_bytes !== null && database.measured_at !== null

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
      {database.quota_state === 'readonly' && (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          This database is over its allowance and has been made read-only. Your
          app can still read, but every write is rejected until usage drops back
          under the allowance or the plan grows.
        </Alert>
      )}
      {database.quota_state === 'blocked' && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          This database is suspended for being far over its allowance. Your app
          cannot connect to it at all until usage drops back under the allowance
          or the plan grows.
        </Alert>
      )}

      <Row label="Database" value={database.database} />
      <Row label="Role" value={database.role} />

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="body2" color="text.secondary" sx={{ minWidth: 96 }}>
          Password
        </Typography>
        {database.password === null ? (
          // Withheld from an administrator, and said so rather than shown as an
          // empty field or an error: nothing here failed.
          <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
            {database.password_withheld
              ? 'Withheld — only the owner can read this'
              : 'Not available'}
          </Typography>
        ) : (
          <>
            <Typography
              variant="body2"
              data-feedback-redact=""
              sx={{ fontFamily: 'monospace', flex: 1, wordBreak: 'break-all' }}
            >
              {revealed ? database.password : MASK}
            </Typography>
            <Tooltip title={revealed ? 'Hide password' : 'Show password'}>
              <IconButton
                size="small"
                aria-label={revealed ? 'Hide password' : 'Show password'}
                onClick={() => setRevealed((v) => !v)}
              >
                {revealed ? (
                  <VisibilityOffIcon fontSize="inherit" />
                ) : (
                  <VisibilityIcon fontSize="inherit" />
                )}
              </IconButton>
            </Tooltip>
            {/* Copyable without revealing: the common action need not put the
                secret on screen. */}
            <CopyButton value={database.password} label="password" />
          </>
        )}
      </Box>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
        <Typography variant="body2" color="text.secondary" sx={{ minWidth: 96 }}>
          Usage
        </Typography>
        <Typography variant="body2" sx={{ flex: 1 }}>
          {measured
            ? formatUsage(database.size_bytes!, database.allowance_bytes)
            : `Not yet measured — allowance ${formatBytes(database.allowance_bytes)}`}
        </Typography>
      </Box>
      {measured && (
        // The figure comes from a periodic sweep, so its age travels with it:
        // without the time it reads as current, and a tenant who has just
        // dropped a large table would conclude the platform is wrong.
        <Typography variant="caption" color="text.secondary" sx={{ ml: '104px' }}>
          Measured {formatDateTime(database.measured_at)}
        </Typography>
      )}

      <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5 }}>
        This database is reachable from your running app, which already has these
        details in its environment. It is not reachable from this computer.
      </Typography>
    </Box>
  )
}
