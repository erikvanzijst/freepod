import { Button, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle } from '@mui/material'

interface DisconnectGitHubDialogProps {
  login: string
  pending: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function DisconnectGitHubDialog({ login, pending, onConfirm, onCancel }: DisconnectGitHubDialogProps) {
  return (
    <Dialog open onClose={onCancel} maxWidth="xs" fullWidth>
      <DialogTitle>Disconnect GitHub?</DialogTitle>
      <DialogContent>
        <DialogContentText>
          Freepod will no longer act for <strong>{login}</strong> on GitHub, and App Studio can no
          longer push to your repositories. The Freepod app stays installed on your GitHub
          accounts; remove it there if you want to.
        </DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>Cancel</Button>
        <Button color="error" variant="contained" disabled={pending} onClick={onConfirm}>
          Disconnect
        </Button>
      </DialogActions>
    </Dialog>
  )
}
