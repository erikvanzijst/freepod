import { Button, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle } from '@mui/material'

interface StopAppDialogProps {
  appName: string
  address: string | null
  onConfirm: () => void
  onCancel: () => void
}

/** Confirms a stop: what stops, what is kept, and what visitors see meanwhile. */
export function StopAppDialog({ appName, address, onConfirm, onCancel }: StopAppDialogProps) {
  return (
    <Dialog open onClose={onCancel} maxWidth="xs" fullWidth>
      <DialogTitle>Stop {appName}?</DialogTitle>
      <DialogContent>
        <DialogContentText sx={{ mb: 2 }}>
          {appName} stops running. Its data is kept, and nothing is deleted.
        </DialogContentText>
        <DialogContentText>
          Until you start it again, visitors to {address ? <strong>{address}</strong> : 'its address'} see a page saying it
          is stopped.
        </DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>Cancel</Button>
        <Button variant="contained" onClick={onConfirm}>Stop app</Button>
      </DialogActions>
    </Dialog>
  )
}
