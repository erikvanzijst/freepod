import { useState } from 'react'
import { Avatar, Box, Button, IconButton, Stack, Typography } from '@mui/material'
import CloseRounded from '@mui/icons-material/CloseRounded'
import MailOutlineRounded from '@mui/icons-material/MailOutlineRounded'
import type { AccessEntry } from '../../api/types'
import { fg, line } from '../landing/landingTokens'
import { toneColor } from '../deployment/deploymentView'
import { Highlight } from './Highlight'
import { initials, shortDay } from './accessText'

const avatarSx = { width: 36, height: 36, fontSize: 13, fontWeight: 600 } as const

export function PersonAvatar({ entry }: { entry: AccessEntry }) {
  if (!entry.bound_at) {
    return (
      <Avatar sx={{ ...avatarSx, background: 'none', border: `1px dashed ${fg.faint}`, color: fg.muted }}>
        <MailOutlineRounded sx={{ fontSize: 17 }} />
      </Avatar>
    )
  }
  return <Avatar sx={{ ...avatarSx, background: 'rgba(91, 140, 255, 0.16)', color: '#8FB0FF' }}>{initials(entry.name, entry.email)}</Avatar>
}

interface AccessEntryRowProps {
  entry: AccessEntry
  appName: string
  search?: string
  /** Removes the entry; absent for a read-only view. */
  onRemove?: (entry: AccessEntry) => Promise<unknown>
}

/** One person on the list; removing them asks for confirmation in the row itself. */
export function AccessEntryRow({ entry, appName, search = '', onRemove }: AccessEntryRowProps) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const who = entry.name || entry.email

  const remove = async () => {
    if (!onRemove) return
    setBusy(true)
    setError(null)
    try {
      await onRemove(entry)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
      setBusy(false)
    }
  }

  if (confirming) {
    return (
      <Box sx={{ my: 0.5, p: 1.5, borderRadius: '10px', border: `1px solid ${toneColor.problem}66`, background: `${toneColor.problem}0F` }}>
        <Stack direction="row" spacing={1.5} alignItems="center">
          <PersonAvatar entry={entry} />
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography sx={{ fontSize: 14.5, fontWeight: 500 }}>Remove {who}?</Typography>
            <Typography sx={{ fontSize: 13, color: fg.muted, lineHeight: 1.45 }}>
              They lose access to {appName} within a minute and can't sign in again. What they stored there stays.
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} sx={{ flex: '0 0 auto' }}>
            <Button size="small" disabled={busy} onClick={() => { setConfirming(false); setError(null) }} sx={{ color: fg.muted }}>
              Cancel
            </Button>
            <Button size="small" variant="contained" disabled={busy} onClick={remove}
              sx={{ background: toneColor.problem, color: '#1A0B0B', '&:hover': { background: '#FCA5A5' } }}>
              {busy ? 'Removing…' : 'Remove'}
            </Button>
          </Stack>
        </Stack>
        {error && <Typography role="alert" sx={{ mt: 1, fontSize: 13, color: toneColor.problem }}>{error}</Typography>}
      </Box>
    )
  }

  return (
    <Stack direction="row" spacing={1.5} alignItems="center" sx={{ py: 1.25, borderBottom: `1px solid ${line.softer}` }}>
      <PersonAvatar entry={entry} />
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography noWrap sx={{ fontSize: 14.5 }}><Highlight text={who} query={search} /></Typography>
        <Typography noWrap sx={{ fontSize: 13, color: fg.muted }}>
          {entry.bound_at ? (
            <>
              <Highlight text={entry.email} query={search} /> · signed in {shortDay(entry.bound_at)}
            </>
          ) : (
            `Invited ${shortDay(entry.created_at)} · hasn't signed in yet`
          )}
        </Typography>
      </Box>
      {onRemove && (
        <IconButton size="small" aria-label={`Remove ${entry.email}`} onClick={() => setConfirming(true)} sx={{ color: fg.faint }}>
          <CloseRounded fontSize="small" />
        </IconButton>
      )}
    </Stack>
  )
}
