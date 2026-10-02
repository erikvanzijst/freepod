import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import AddRoundedIcon from '@mui/icons-material/AddRounded'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import VpnKeyOutlinedIcon from '@mui/icons-material/VpnKeyOutlined'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { addSshKey, deleteSshKey, listSshKeys } from '../api/endpoints'
import type { SshKey } from '../api/types'
import { useAuth } from '../state/AuthContext'
import { parseUtc } from '../utils/formatDate'
import { AddSshKeyDialog } from './AddSshKeyDialog'
import { ConfirmDeleteDialog } from './ConfirmDeleteDialog'
import { CopyButton } from './CopyButton'
import { accent, fg, line, MONO } from './landing/landingTokens'

function formatAdded(iso: string): string {
  const date = parseUtc(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

/** `ssh-ed25519` → `Ed25519`; `sk-ecdsa-...` → `ECDSA (security key)`. */
function describeType(keyType: string, bits: number): string {
  const hardware = keyType.startsWith('sk-')
  const base = keyType.replace(/^sk-/, '').replace(/@openssh\.com$/, '')
  let name = base
  if (base.startsWith('ssh-ed25519')) name = 'Ed25519'
  else if (base.startsWith('ssh-rsa')) name = `RSA ${bits}`
  else if (base.startsWith('ecdsa')) name = `ECDSA ${bits}`
  return hardware ? `${name} · security key` : name
}

function KeyRow({ item, onDelete }: { item: SshKey; onDelete: (key: SshKey) => void }) {
  // An unlabeled key is named by its fingerprint rather than a placeholder:
  // the fingerprint is the identity, and inventing a label here would be the
  // same mistake the platform deliberately does not make.
  const titled = Boolean(item.label)
  return (
    <Stack
      direction="row"
      alignItems="flex-start"
      spacing={1.5}
      sx={{
        py: 2,
        px: { xs: 0, sm: 0.5 },
        borderRadius: 2,
        transition: 'background 0.15s',
        '&:hover': { background: 'rgba(255,255,255,0.02)' },
        '&:hover .key-actions': { opacity: 1 },
      }}
    >
      <Box
        sx={{
          mt: 0.25,
          width: 34,
          height: 34,
          flexShrink: 0,
          borderRadius: '50%',
          display: 'grid',
          placeItems: 'center',
          color: accent.cyan,
          border: `1px solid ${line.soft}`,
          background: 'rgba(56,189,248,0.08)',
        }}
      >
        <VpnKeyOutlinedIcon fontSize="small" />
      </Box>

      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.25, minWidth: 0 }}>
          <Typography
            noWrap
            sx={
              titled
                ? { fontWeight: 600 }
                : { fontWeight: 600, fontFamily: MONO, fontSize: 13.5 }
            }
            title={titled ? undefined : item.fingerprint}
          >
            {titled ? item.label : item.fingerprint}
          </Typography>
          <Chip
            size="small"
            variant="outlined"
            label={describeType(item.key_type, item.bits)}
            sx={{ height: 20, fontSize: 11, color: fg.muted, flexShrink: 0 }}
          />
          {!titled && <CopyButton value={item.fingerprint} label="fingerprint" />}
        </Stack>
        {titled && (
          <Stack direction="row" alignItems="center" spacing={0.5} sx={{ minWidth: 0 }}>
            <Typography
              sx={{
                fontFamily: MONO,
                fontSize: 12.5,
                color: fg.muted,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              title={item.fingerprint}
            >
              {item.fingerprint}
            </Typography>
            <CopyButton value={item.fingerprint} label="fingerprint" />
          </Stack>
        )}
        <Typography variant="caption" color="text.secondary">
          Added {formatAdded(item.created_at)}
        </Typography>
      </Box>

      <Box className="key-actions" sx={{ opacity: { xs: 1, md: 0.35 }, transition: 'opacity 0.15s' }}>
        <Tooltip title="Remove this key">
          <IconButton
            size="small"
            aria-label={`Remove ${item.label ?? item.fingerprint}`}
            onClick={() => onDelete(item)}
          >
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
    </Stack>
  )
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <Box sx={{ py: 5, textAlign: 'center' }}>
      <Box
        sx={{
          width: 52,
          height: 52,
          mx: 'auto',
          mb: 2,
          borderRadius: '50%',
          display: 'grid',
          placeItems: 'center',
          color: accent.cyan,
          border: `1px solid ${line.soft}`,
          background: 'rgba(56,189,248,0.06)',
        }}
      >
        <VpnKeyOutlinedIcon />
      </Box>
      <Typography variant="h6" sx={{ mb: 0.5 }}>
        No SSH keys yet
      </Typography>
      <Typography color="text.secondary" sx={{ maxWidth: 460, mx: 'auto', mb: 2.5 }}>
        An SSH key identifies you to the platform without a password. Paste a public
        key you already have, or run <code>freepod key add</code> to create one and
        register it in a single step.
      </Typography>
      <Button variant="contained" startIcon={<AddRoundedIcon />} onClick={onAdd}>
        Add SSH key
      </Button>
    </Box>
  )
}

/**
 * Manages the account's SSH public keys.
 *
 * The keys are the SSH credential the edge resolves connections against, but
 * this panel is about registering and revoking them; the copy says what a key
 * is, not what a connection does.
 */
export function SshKeysPanel() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<SshKey | null>(null)

  const keysQuery = useQuery({
    queryKey: ['ssh-keys', user?.id],
    queryFn: () => listSshKeys(user!.id),
    enabled: Boolean(user?.id),
  })

  const addMutation = useMutation({
    mutationFn: (payload: { public_key: string; label?: string }) =>
      addSshKey(user!.id, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['ssh-keys'] })
      setAddOpen(false)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (fingerprint: string) => deleteSshKey(user!.id, fingerprint),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['ssh-keys'] })
      setDeleteTarget(null)
    },
  })

  const keys = keysQuery.data ?? []

  return (
    <Card sx={{ p: { xs: 2.5, sm: 3 } }}>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        alignItems={{ xs: 'flex-start', sm: 'center' }}
        sx={{ mb: 1 }}
      >
        <Box sx={{ flex: 1 }}>
          <Typography variant="h6">SSH keys</Typography>
          <Typography color="text.secondary" variant="body2" sx={{ mt: 0.5 }}>
            Public keys that identify you to the platform. They belong to your
            account and apply to every app you own.
          </Typography>
        </Box>
        {keys.length > 0 && (
          <Button
            variant="contained"
            startIcon={<AddRoundedIcon />}
            onClick={() => setAddOpen(true)}
            sx={{ flexShrink: 0 }}
          >
            Add key
          </Button>
        )}
      </Stack>

      {keysQuery.isLoading && (
        <Stack alignItems="center" sx={{ py: 6 }}>
          <CircularProgress size={22} />
        </Stack>
      )}

      {keysQuery.error != null && (
        <Alert severity="error" variant="outlined" sx={{ mt: 2 }}>
          Could not load your SSH keys.
        </Alert>
      )}

      {!keysQuery.isLoading && keysQuery.error == null && (
        keys.length === 0 ? (
          <EmptyState onAdd={() => setAddOpen(true)} />
        ) : (
          <Box sx={{ mt: 1 }}>
            {keys.map((item, index) => (
              <Box key={item.fingerprint}>
                {index > 0 && <Divider />}
                <KeyRow item={item} onDelete={setDeleteTarget} />
              </Box>
            ))}
          </Box>
        )
      )}

      <AddSshKeyDialog
        open={addOpen}
        pending={addMutation.isPending}
        error={addMutation.error}
        onAdd={(payload) => addMutation.mutate(payload)}
        onClose={() => {
          addMutation.reset()
          setAddOpen(false)
        }}
      />

      {deleteTarget && (
        <ConfirmDeleteDialog
          subject="SSH key"
          name={deleteTarget.label ?? deleteTarget.fingerprint}
          consequence="Any machine holding this key will lose access."
          onConfirm={() => deleteMutation.mutate(deleteTarget.fingerprint)}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </Card>
  )
}

export default SshKeysPanel
