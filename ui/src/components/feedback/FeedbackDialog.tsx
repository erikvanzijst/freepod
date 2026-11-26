import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogContent,
  IconButton,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import CloseRoundedIcon from '@mui/icons-material/CloseRounded'
import CheckCircleOutlineRoundedIcon from '@mui/icons-material/CheckCircleOutlineRounded'
import { useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { submitFeedback } from '../../api/endpoints'
import type { FeedbackTopic } from '../../api/types'
import { useAuth } from '../../state/AuthContext'
import { accent, cardSurface, DISPLAY, fg, ink, MONO } from '../landing/landingTokens'
import { FEEDBACK_UI_ATTR } from './capture'
import { snapshot } from './diagnostics'
import type { FeedbackSession } from './FeedbackProvider'
import { FeedbackScreenshot } from './FeedbackScreenshot'
import { FeedbackSignInGate } from './FeedbackSignInGate'
import { THANKS_MS, TOPICS } from './topics'

const MESSAGE_MAX = 5000
const UI_BUILD = (import.meta.env.VITE_GIT_COMMIT as string | undefined) || 'dev'

function useScreenshot(pending: Promise<Blob | null> | null) {
  const [image, setImage] = useState<Blob | null>(null)
  const [waiting, setWaiting] = useState(Boolean(pending))
  useEffect(() => {
    if (!pending) return
    let live = true
    pending.then((blob) => {
      if (!live) return
      setImage(blob)
      setWaiting(false)
    })
    return () => {
      live = false
    }
  }, [pending])
  return { image, waiting }
}

export function FeedbackDialog({ session, onClose }: { session: FeedbackSession; onClose: () => void }) {
  const { user, loading } = useAuth()
  const { image, waiting } = useScreenshot(session.screenshot)
  const [removed, setRemoved] = useState(false)
  const [topic, setTopic] = useState<FeedbackTopic | null>(null)
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)

  useEffect(() => {
    if (!sent) return
    const timer = setTimeout(onClose, THANKS_MS)
    return () => clearTimeout(timer)
  }, [sent, onClose])

  const canSend = Boolean(topic) && message.trim().length > 0 && !sending

  async function send() {
    if (!topic) return
    setSending(true)
    setError(null)
    try {
      const screenshot = removed || !session.screenshot ? null : await session.screenshot
      await submitFeedback({
        topic,
        message,
        page: session.page,
        userAgent: navigator.userAgent,
        viewport: `${window.innerWidth}x${window.innerHeight}`,
        uiBuild: UI_BUILD,
        diagnostics: snapshot(),
        screenshot,
      })
      setSent(true)
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : 'Sending failed. Please try again.')
    } finally {
      setSending(false)
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      aria-labelledby="feedback-title"
      {...{ [FEEDBACK_UI_ATTR]: '' }}
      slotProps={{
        paper: {
          sx: {
            backgroundColor: ink.raised,
            backgroundImage: `linear-gradient(160deg, #161d38, ${ink.raised})`,
            border: cardSurface.border,
            borderRadius: '12px',
          },
        },
      }}
    >
      <IconButton aria-label="Close" onClick={onClose} sx={{ position: 'absolute', top: 10, right: 10, color: fg.muted }}>
        <CloseRoundedIcon fontSize="small" />
      </IconButton>
      <DialogContent sx={{ p: { xs: 3, sm: 4 } }}>
        <Typography sx={{ fontFamily: MONO, fontSize: 12, letterSpacing: '0.22em', color: accent.cyan, mb: 1 }}>
          FEEDBACK
        </Typography>
        <Typography id="feedback-title" component="h2" sx={{ fontFamily: DISPLAY, fontSize: 28, fontWeight: 600, lineHeight: 1.15, mb: 1 }}>
          {sent ? 'Thank you' : 'Help make Freepod better'}
        </Typography>
        {sent ? (
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ color: fg.muted }} role="status">
            <CheckCircleOutlineRoundedIcon sx={{ color: 'success.main' }} />
            <Typography>We read every message. Your feedback is on its way to the team.</Typography>
          </Stack>
        ) : loading ? null : !user ? (
          <FeedbackSignInGate page={session.page} onClose={onClose} />
        ) : (
          <Stack spacing={2.5}>
            <Typography sx={{ color: fg.muted }}>Tell us what is wrong, what you miss, or what you like.</Typography>
            <Box role="radiogroup" aria-label="Topic" sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
              {TOPICS.map((t) => (
                <Chip
                  key={t.value}
                  role="radio"
                  aria-checked={topic === t.value}
                  label={t.label}
                  clickable
                  color={topic === t.value ? 'primary' : 'default'}
                  variant={topic === t.value ? 'filled' : 'outlined'}
                  onClick={() => setTopic(t.value)}
                />
              ))}
            </Box>
            <TextField
              label="Your message"
              multiline
              minRows={4}
              maxRows={12}
              fullWidth
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              slotProps={{ htmlInput: { maxLength: MESSAGE_MAX } }}
            />
            {!removed && <FeedbackScreenshot pending={waiting} image={image} onRemove={() => setRemoved(true)} />}
            {error && <Alert severity="error">{error}</Alert>}
            <Typography variant="body2" sx={{ color: fg.faint }}>
              Sent with your account, this page’s address{removed || (!waiting && !image) ? '' : ', the screenshot'} and
              technical details such as your browser and recent errors.
            </Typography>
            <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1.5 }}>
              <Button variant="outlined" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant="contained"
                onClick={send}
                disabled={!canSend}
                startIcon={sending ? <CircularProgress size={16} color="inherit" /> : undefined}
              >
                Send
              </Button>
            </Box>
          </Stack>
        )}
      </DialogContent>
    </Dialog>
  )
}

export default FeedbackDialog
