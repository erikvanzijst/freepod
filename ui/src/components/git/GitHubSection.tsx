import { useEffect, useRef, useState } from 'react'
import { Alert, Box, Button, Stack, Typography } from '@mui/material'
import AddRoundedIcon from '@mui/icons-material/AddRounded'
import GitHubIcon from '@mui/icons-material/GitHub'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  disconnectGitHub,
  listGitHubInstallations,
  startGitHubConnect,
} from '../../api/endpoints'
import { ApiError } from '../../api/client'
import type { GitConnection, GitHubConnectStart } from '../../api/types'
import { parseUtc } from '../../utils/formatDate'
import { accent, line } from '../landing/landingTokens'
import { AppStudioLink } from './AppStudioLink'
import { DisconnectGitHubDialog } from './DisconnectGitHubDialog'
import { GitHubInstallations } from './GitHubInstallations'
import { gitErrorMessage } from './gitOutcome'
import { redirectTo } from './redirect'

function formatDate(iso: string): string {
  const date = parseUtc(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function errorMessage(error: unknown): string {
  return gitErrorMessage(error instanceof ApiError ? error.code : undefined)
}

function GitHubBadge() {
  return (
    <Box
      sx={{
        width: 40,
        height: 40,
        flexShrink: 0,
        borderRadius: '50%',
        display: 'grid',
        placeItems: 'center',
        color: accent.cyan,
        border: `1px solid ${line.soft}`,
        background: 'rgba(56,189,248,0.08)',
      }}
    >
      <GitHubIcon />
    </Box>
  )
}

interface GitHubSectionProps {
  userId: number
  connection: GitConnection | undefined
  /** Start authorizing at once, as a link from `freepod git connect` asks. */
  autoConnect?: boolean
  onAutoConnect?: () => void
}

/** Connecting to GitHub, and once connected, the account and its installations. */
export function GitHubSection({ userId, connection, autoConnect, onAutoConnect }: GitHubSectionProps) {
  const queryClient = useQueryClient()
  const [confirmDisconnect, setConfirmDisconnect] = useState(false)

  const connect = useMutation({
    mutationFn: (target: keyof GitHubConnectStart) =>
      startGitHubConnect(userId).then((links) => links[target]),
    onSuccess: (url) => redirectTo(url),
  })

  const autoStarted = useRef(false)
  useEffect(() => {
    if (!autoConnect || autoStarted.current) return
    autoStarted.current = true
    onAutoConnect?.()
    if (!connection) connect.mutate('authorize_url')
  }, [autoConnect, connection, connect, onAutoConnect])

  const installations = useQuery({
    queryKey: ['git', userId, 'github', 'installations'],
    queryFn: () => listGitHubInstallations(userId),
    enabled: Boolean(connection),
    retry: false,
  })

  const lost = installations.error instanceof ApiError && installations.error.code === 'git_not_connected'
  useEffect(() => {
    if (lost) void queryClient.invalidateQueries({ queryKey: ['git', userId, 'connections'] })
  }, [lost, queryClient, userId])

  const disconnect = useMutation({
    mutationFn: () => disconnectGitHub(userId),
    onSuccess: () => {
      setConfirmDisconnect(false)
      void queryClient.invalidateQueries({ queryKey: ['git', userId] })
    },
  })

  return (
    <Box>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ xs: 'flex-start', sm: 'center' }}>
        <GitHubBadge />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontWeight: 600 }}>GitHub</Typography>
          {connection ? (
            <Typography variant="body2" color="text.secondary">
              Connected as{' '}
              <Box
                component="a"
                href={`https://github.com/${connection.login}`}
                target="_blank"
                rel="noopener noreferrer"
                sx={{ color: 'text.primary', fontWeight: 600 }}
              >
                {connection.login}
              </Box>{' '}
              since {formatDate(connection.connected_at)}
            </Typography>
          ) : (
            <Typography variant="body2" color="text.secondary">
              Let <AppStudioLink /> or the freepod cli create repositories for your apps, push their code, and link deployments to the
              repositories they are built from.
            </Typography>
          )}
        </Box>
        {connection ? (
          <Button color="inherit" onClick={() => setConfirmDisconnect(true)} sx={{ flexShrink: 0 }}>
            Disconnect
          </Button>
        ) : (
          <Button
            variant="contained"
            startIcon={<GitHubIcon />}
            disabled={connect.isPending}
            onClick={() => connect.mutate('authorize_url')}
            sx={{ flexShrink: 0 }}
          >
            Connect GitHub
          </Button>
        )}
      </Stack>

      {connect.error != null && (
        <Alert severity="error" variant="outlined" sx={{ mt: 2 }}>
          {errorMessage(connect.error)}
        </Alert>
      )}

      {connection && (
        <Box sx={{ mt: 3 }}>
          <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: 0.5 }}>
            <Box sx={{ flex: 1 }}>
              <Typography variant="subtitle2">Repository access</Typography>
              <Typography variant="body2" color="text.secondary">
                Freepod reaches only the repositories you grant the Freepod app, account by
                account.
              </Typography>
            </Box>
            <Button
              size="small"
              startIcon={<AddRoundedIcon />}
              disabled={connect.isPending}
              onClick={() => connect.mutate('install_url')}
              sx={{ flexShrink: 0 }}
            >
              Add account
            </Button>
          </Stack>
          <GitHubInstallations
            installations={installations.data}
            loading={installations.isLoading}
            failed={installations.error != null && !lost}
          />
        </Box>
      )}

      {disconnect.error != null && (
        <Alert severity="error" variant="outlined" sx={{ mt: 2 }}>
          {errorMessage(disconnect.error)}
        </Alert>
      )}

      {confirmDisconnect && connection && (
        <DisconnectGitHubDialog
          login={connection.login}
          pending={disconnect.isPending}
          onConfirm={() => disconnect.mutate()}
          onCancel={() => setConfirmDisconnect(false)}
        />
      )}
    </Box>
  )
}
