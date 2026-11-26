import { Button, Link, Stack, Typography } from '@mui/material'
import { useLocation, useNavigate } from 'react-router-dom'
import EmailDialog from '../EmailDialog'
import useStartSignup from '../landing/useStartSignup'
import { fg } from '../landing/landingTokens'

export const FEEDBACK_ADDRESS = 'feedback@freepod.eu'

/** D10: signing in returns to this page with the dialog open, naming `page`. */
export function FeedbackSignInGate({ page, onClose }: { page: string; onClose: () => void }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { start, dialogOpen, setDialogOpen, setEmail, returnTo } = useStartSignup()
  const back = `${location.pathname}?feedback=1&from=${encodeURIComponent(page)}`

  return (
    <Stack spacing={2.5}>
      <Typography sx={{ color: fg.muted }}>
        Feedback is sent from your Freepod account, so we know who it is from and can get back to you.
        Sign in to continue, or email us at{' '}
        <Link href={`mailto:${FEEDBACK_ADDRESS}`}>{FEEDBACK_ADDRESS}</Link>.
      </Typography>
      <Stack direction="row" spacing={1.5}>
        <Button variant="contained" onClick={() => start(back)}>
          Sign in
        </Button>
        <Button variant="outlined" onClick={onClose}>
          Not now
        </Button>
      </Stack>
      <EmailDialog
        open={dialogOpen}
        onSave={(email) => {
          setEmail(email)
          setDialogOpen(false)
          navigate(returnTo)
        }}
      />
    </Stack>
  )
}

export default FeedbackSignInGate
