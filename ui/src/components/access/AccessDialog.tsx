import { useState } from 'react'
import {
  Avatar,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  Stack,
  Typography,
} from '@mui/material'
import PeopleOutlineRounded from '@mui/icons-material/PeopleOutlineRounded'
import { fg, line } from '../landing/landingTokens'
import { SearchField } from '../appsgallery/GalleryParts'
import { AccessEntryRow } from './AccessEntryRow'
import { AccessAddForm } from './AccessAddForm'
import { AccessFilterChips } from './AccessFilterChips'
import { addError, filterEntries, type AccessFilter } from './accessText'
import { useAccessList } from './useAccessList'

/** Past this many entries the list offers search and filters (app-access-dialog). */
const SEARCHABLE = 10

interface AccessDialogProps {
  userId: number
  deploymentId: string
  hostname: string | null | undefined
  appName: string
  onClose: () => void
}

/**
 * Who may sign in to a `listed` deployment: the owner, always, and the list
 * the owner keeps. Nothing here depends on the product but its name and
 * address.
 */
export function AccessDialog({ userId, deploymentId, hostname, appName, onClose }: AccessDialogProps) {
  const { query, add, remove } = useAccessList(userId, deploymentId)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<AccessFilter>('all')
  const access = query.data
  const entries = access?.entries ?? []
  const searchable = entries.length > SEARCHABLE
  const shown = searchable ? filterEntries(entries, search, filter) : entries
  const narrowed = searchable && (search.trim() !== '' || filter !== 'all')

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth scroll="paper" slotProps={{ paper: { sx: { height: searchable ? '86vh' : undefined } } }}>
      <DialogTitle>
        <Stack direction="row" spacing={1.5} alignItems="center">
          <PeopleOutlineRounded color="primary" />
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="h6" noWrap>Access</Typography>
            {hostname && <Typography variant="body2" color="text.secondary" noWrap>{hostname}</Typography>}
          </Box>
        </Stack>
      </DialogTitle>
      <DialogContent dividers={false} sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>
        {!searchable && (
          <Typography sx={{ fontSize: 14.5, color: fg.muted, mb: 2.5, lineHeight: 1.55 }}>
            Only you and the people on this list can sign in to {appName}. They sign in with a Freepod account that uses
            the address you add here.
          </Typography>
        )}
        <Box sx={{ pt: 1 }}>
          <AccessAddForm
            onAdd={async (email) => { await add.mutateAsync(email) }}
            describeError={(err, email) => addError(err, email, access?.owner_email ?? '', access?.limit ?? 500)}
          />
        </Box>

        {query.isPending && <LinearProgress sx={{ my: 2 }} />}
        {query.isError && (
          <Typography role="alert" sx={{ fontSize: 14, color: fg.muted, my: 2 }}>
            The list could not be loaded. Close this and try again.
          </Typography>
        )}
        {access && (
          <>
            {searchable ? (
              <Box sx={{ borderTop: `1px solid ${line.soft}`, pt: 2, pb: 1 }}>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25} alignItems={{ sm: 'center' }}>
                  <Box sx={{ flex: 1 }}>
                    <SearchField value={search} onChange={setSearch} placeholder="Search people" fullWidth />
                  </Box>
                  <AccessFilterChips value={filter} onChange={setFilter} />
                </Stack>
                <Typography sx={{ fontSize: 13, color: fg.faint, mt: 1 }}>
                  {narrowed ? `${shown.length} of ${entries.length} people match` : `${entries.length} people`}
                </Typography>
              </Box>
            ) : (
              <Typography sx={{ fontSize: 13, color: fg.faint, mb: 0.5 }}>
                {entries.length + 1} {entries.length === 0 ? 'person' : 'people'} can sign in
              </Typography>
            )}
            <Box sx={{ flex: 1, minHeight: 0, overflowY: 'auto', mx: -1, px: 1 }} data-testid="access-list">
              {!narrowed && <OwnerRow email={access.owner_email} />}
              {shown.map((entry) => (
                <AccessEntryRow
                  key={entry.id}
                  entry={entry}
                  appName={appName}
                  search={search}
                  onRemove={(e) => remove.mutateAsync(e.id)}
                />
              ))}
            </Box>
            <Box sx={{ mt: 2, p: searchable ? 0 : 1.5, borderRadius: '10px', background: searchable ? 'none' : 'rgba(91, 140, 255, 0.08)' }}>
              <Typography sx={{ fontSize: 13, color: fg.muted, lineHeight: 1.5 }}>
                {searchable
                  ? `You (owner) always have access. ${entries.length} of ${access.limit} places used.`
                  : `We email everyone you add a link to ${appName}. The first time they sign in, their place on the list is tied to their Freepod account.`}
              </Typography>
            </Box>
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Done</Button>
      </DialogActions>
    </Dialog>
  )
}

function OwnerRow({ email }: { email: string }) {
  return (
    <Stack direction="row" spacing={1.5} alignItems="center" sx={{ py: 1.25, borderBottom: `1px solid ${line.softer}` }}>
      <Avatar sx={{ width: 36, height: 36, fontSize: 13, fontWeight: 600, background: 'rgba(91, 140, 255, 0.16)', color: '#8FB0FF' }}>
        {email.slice(0, 2).toUpperCase()}
      </Avatar>
      <Box sx={{ minWidth: 0 }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography sx={{ fontSize: 14.5 }}>You</Typography>
          <Chip label="Owner" size="small" sx={{ height: 20, fontSize: 12 }} />
        </Stack>
        <Typography noWrap sx={{ fontSize: 13, color: fg.muted }}>{email} · always has access</Typography>
      </Box>
    </Stack>
  )
}
