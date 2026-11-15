import { useState } from 'react'
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Stack,
  Typography,
} from '@mui/material'
import DescriptionOutlined from '@mui/icons-material/DescriptionOutlined'

interface ManagedFieldNoticeProps {
  /** The field's label, e.g. "Name" or "Sign in with Freepod". */
  label: string
  /** Absent while a take-over cannot be offered, e.g. during a save. */
  onTakeOver?: () => void
  takingOver?: boolean
}

/** Marks a field `.freepod.json` manages, with Take over behind a confirmation. */
export function ManagedFieldNotice({ label, onTakeOver, takingOver }: ManagedFieldNoticeProps) {
  const [confirming, setConfirming] = useState(false)
  return (
    <Stack direction="row" alignItems="center" spacing={1} sx={{ color: 'text.secondary' }}>
      <DescriptionOutlined sx={{ fontSize: 16 }} />
      <Typography variant="body2" sx={{ flex: 1 }}>
        {label} is managed by <code>.freepod.json</code>
      </Typography>
      {onTakeOver && (
        <Button size="small" disabled={takingOver} onClick={() => setConfirming(true)}>
          Take over
        </Button>
      )}
      {confirming && (
        <Dialog open onClose={() => setConfirming(false)} maxWidth="xs">
          <DialogTitle>Edit {label} here?</DialogTitle>
          <DialogContent>
            <DialogContentText>
              {label} becomes editable on the dashboard. The next <code>freepod apply</code> or{' '}
              <code>freepod deploy</code> from a <code>.freepod.json</code> that still sets it puts its value back.
            </DialogContentText>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setConfirming(false)}>Cancel</Button>
            <Button
              variant="contained"
              onClick={() => {
                setConfirming(false)
                onTakeOver?.()
              }}
            >
              Take over
            </Button>
          </DialogActions>
        </Dialog>
      )}
    </Stack>
  )
}
