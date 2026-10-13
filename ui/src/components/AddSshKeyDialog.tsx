import { useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined'
import { ApiError } from '../api/client'
import { accent, fg, MONO } from './landing/landingTokens'

/** A `.pub` file is a few hundred bytes; anything larger is not one. */
const MAX_KEY_FILE_BYTES = 64 * 1024

/**
 * How each refusal reads to a user, keyed by the platform's stable `code`.
 *
 * Keyed by code and never by message text: several of these share HTTP 400,
 * and the platform is free to reword its prose without breaking this mapping.
 */
const REFUSALS: Record<string, string> = {
  malformed_key:
    "That does not look like an OpenSSH public key. It should be one line beginning with a type such as 'ssh-ed25519'.",
  private_key_material:
    'That is a private key. Paste the public half instead: the file ending in .pub. Never share the private one.',
  multiple_keys: 'That is more than one key. Add them one at a time.',
  unsupported_key_type:
    'That key type is not supported. Use Ed25519, ECDSA, RSA, or a FIDO security key.',
  key_type_mismatch: "The key's declared type does not match its contents.",
  key_too_short: 'That RSA key is too short. Use at least 2048 bits, or an Ed25519 key.',
  duplicate_key: 'That key is already registered on your account.',
}

/** Detects private key material before anything is sent anywhere. */
function looksPrivate(text: string): boolean {
  return /-----BEGIN[ A-Z]*PRIVATE KEY-----/i.test(text)
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code && REFUSALS[error.code]) return REFUSALS[error.code]
    return error.message
  }
  return 'Something went wrong adding that key.'
}

interface AddSshKeyDialogProps {
  open: boolean
  pending: boolean
  error: unknown
  onAdd: (payload: { public_key: string; label?: string }) => void
  onClose: () => void
}

export function AddSshKeyDialog({
  open,
  pending,
  error,
  onAdd,
  onClose,
}: AddSshKeyDialogProps) {
  const [publicKey, setPublicKey] = useState('')
  const [label, setLabel] = useState('')
  const [dragging, setDragging] = useState(false)
  const [fileError, setFileError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const dragDepth = useRef(0)

  const isPrivate = looksPrivate(publicKey)
  const canSubmit = publicKey.trim().length > 0 && !isPrivate && !pending

  async function acceptFile(file: File) {
    setFileError(null)
    if (file.size > MAX_KEY_FILE_BYTES) {
      setFileError(`${file.name} is too large to be a public key file.`)
      return
    }
    const text = await file.text()
    // Refused rather than loaded. A drop is the one path where the private
    // half can be kept out of the page entirely, and putting it in the
    // textarea would be displaying it.
    if (looksPrivate(text)) {
      setFileError(
        `${file.name} is a private key. It must never leave your machine. ` +
          `Drop ${file.name}.pub instead.`,
      )
      return
    }
    setPublicKey(text.trim())
  }

  function handleDrop(event: React.DragEvent) {
    event.preventDefault()
    dragDepth.current = 0
    setDragging(false)
    const file = event.dataTransfer.files?.[0]
    if (file) void acceptFile(file)
  }

  /** Clears every field. Runs after the close animation, whatever closed it. */
  function reset() {
    setPublicKey('')
    setLabel('')
    setFileError(null)
    setDragging(false)
    dragDepth.current = 0
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      // Reset on exit rather than in a close handler: the dialog is also
      // closed from outside after a successful add, and this component stays
      // mounted throughout, so a per-handler reset misses that path and the
      // next open still holds the last key.
      slotProps={{ transition: { onExited: reset } }}
    >
      <DialogTitle>Add an SSH key</DialogTitle>
      <DialogContent
        onDragEnter={(e) => {
          e.preventDefault()
          dragDepth.current += 1
          setDragging(true)
        }}
        onDragOver={(e) => e.preventDefault()}
        onDragLeave={(e) => {
          e.preventDefault()
          dragDepth.current -= 1
          if (dragDepth.current <= 0) setDragging(false)
        }}
        onDrop={handleDrop}
        sx={{ position: 'relative' }}
      >
        {/* Covers the content while a file is over it, so the whole dialog is
            one target rather than a small strip the user has to find. */}
        {dragging && (
          <Box
            sx={{
              position: 'absolute',
              inset: 8,
              zIndex: 2,
              borderRadius: '12px',
              border: `1.5px dashed ${accent.cyan}`,
              background: 'rgba(56,189,248,0.07)',
              backdropFilter: 'blur(2px)',
              display: 'grid',
              placeItems: 'center',
              pointerEvents: 'none',
            }}
          >
            <Stack alignItems="center" spacing={1}>
              <UploadFileOutlinedIcon sx={{ color: accent.cyan }} />
              <Typography variant="body2" sx={{ color: accent.cyan, fontWeight: 600 }}>
                Drop your .pub file
              </Typography>
            </Stack>
          </Box>
        )}
        <DialogContentText sx={{ mb: 2 }}>
          Paste a public key in OpenSSH format: one line, starting with its type.
          It is usually in <code>~/.ssh/id_ed25519.pub</code>.
        </DialogContentText>
        <Stack spacing={2}>
          <TextField
            autoFocus
            fullWidth
            multiline
            minRows={3}
            maxRows={8}
            label="Public key"
            placeholder="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5... you@laptop"
            value={publicKey}
            onChange={(e) => setPublicKey(e.target.value)}
            slotProps={{
              htmlInput: { style: { fontFamily: MONO, fontSize: 13, lineHeight: 1.6 } },
            }}
          />
          <Stack direction="row" alignItems="center" spacing={0.75} sx={{ mt: -1 }}>
            <UploadFileOutlinedIcon sx={{ fontSize: 15, color: fg.faint }} />
            <Typography variant="caption" sx={{ color: fg.faint }}>
              Drop your <code>.pub</code> file here, or{' '}
              <Box
                component="button"
                type="button"
                onClick={() => fileInput.current?.click()}
                sx={{
                  p: 0,
                  border: 0,
                  background: 'none',
                  font: 'inherit',
                  color: accent.cyan,
                  cursor: 'pointer',
                  textDecoration: 'underline',
                  textUnderlineOffset: 2,
                  '&:hover': { color: fg.primary },
                }}
              >
                browse
              </Box>
              .
            </Typography>
          </Stack>
          <Box
            component="input"
            ref={fileInput}
            type="file"
            accept=".pub,text/plain"
            hidden
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
              const file = e.target.files?.[0]
              if (file) void acceptFile(file)
              e.target.value = ''
            }}
          />
          {fileError && (
            <Alert severity="error" variant="outlined" onClose={() => setFileError(null)}>
              {fileError}
            </Alert>
          )}
          {/* Caught here, before submission: private key material must never
              leave the machine, so this is not left to the platform to refuse. */}
          {isPrivate && (
            <Alert severity="error" variant="outlined">
              That is a <strong>private</strong> key. It must never leave your machine.
              Paste the matching <code>.pub</code> file instead.
            </Alert>
          )}
          <TextField
            fullWidth
            label="Label (optional)"
            placeholder="Work laptop"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            helperText="Helps you tell your keys apart later. Defaults to the key's comment."
          />
          {error != null && !isPrivate && (
            <Alert severity="error" variant="outlined">
              {messageFor(error)}
            </Alert>
          )}
          <Typography variant="body2" color="text.secondary">
            No key yet? Run <code>freepod key add</code> to create one and register it
            in a single step. Keys are never generated in the browser, so the private
            half stays on your machine.
          </Typography>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={!canSubmit}
          onClick={() =>
            onAdd({
              public_key: publicKey.trim(),
              ...(label.trim() ? { label: label.trim() } : {}),
            })
          }
          startIcon={pending ? <CircularProgress size={16} color="inherit" /> : undefined}
        >
          {pending ? 'Adding' : 'Add key'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default AddSshKeyDialog
