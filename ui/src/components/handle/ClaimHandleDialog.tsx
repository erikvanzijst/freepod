import { Dialog, DialogContent } from '@mui/material'
import { ClaimHandle } from './ClaimHandle'

interface ClaimHandleDialogProps {
  open: boolean
  /** The tenant domain, e.g. `freepod.app`. */
  domain: string
  email: string
  onClose: () => void
  /** Called once the handle is held, so a deploy the claim interrupted can go on. */
  onClaimed?: (handle: string) => void
}

/**
 * The picker as a modal, for the deploy path only: the user acted, something
 * interrupts, and they are returned to what they were doing. The dashboard
 * renders the same picker inline instead — a modal nobody opened is an
 * interruption of nothing.
 */
export function ClaimHandleDialog({ open, domain, email, onClose, onClaimed }: ClaimHandleDialogProps) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogContent sx={{ p: 3.75 }}>
        <ClaimHandle
          domain={domain}
          email={email}
          onDismiss={onClose}
          onClaimed={onClaimed}
          autoSelect={open}
        />
      </DialogContent>
    </Dialog>
  )
}
