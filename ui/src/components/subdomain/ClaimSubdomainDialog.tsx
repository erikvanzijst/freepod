import { Dialog, DialogContent } from '@mui/material'
import { ClaimSubdomain } from './ClaimSubdomain'

interface ClaimSubdomainDialogProps {
  open: boolean
  /** The platform domain, e.g. `freepod.eu`. */
  domain: string
  email: string
  onClose: () => void
  /** Called once the domain name is held, so a deploy the claim interrupted can go on. */
  onClaimed?: (subdomain: string) => void
}

/**
 * The picker as a modal, for the deploy path only: the user acted, something
 * interrupts, and they are returned to what they were doing. The dashboard
 * renders the same picker inline instead — a modal nobody opened is an
 * interruption of nothing.
 */
export function ClaimSubdomainDialog({ open, domain, email, onClose, onClaimed }: ClaimSubdomainDialogProps) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogContent sx={{ p: 3.75 }}>
        <ClaimSubdomain
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
