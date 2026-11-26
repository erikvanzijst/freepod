import {
  Alert,
  Box,
  Button,
  ButtonBase,
  Chip,
  CircularProgress,
  Dialog,
  Link,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import MailOutlineRoundedIcon from '@mui/icons-material/MailOutlineRounded'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link as RouterLink, useParams } from 'react-router-dom'
import { getFeedback, getFeedbackScreenshot, setFeedbackResolved } from '../../../api/endpoints'
import type { Feedback, FeedbackDiagnostic } from '../../../api/types'
import { formatLocalIso } from '../../../utils/formatDate'
import { TOPIC_LABELS } from '../topics'
import { FEEDBACK_QUERY_KEY } from './useFeedbackUnread'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Box sx={{ display: 'flex', gap: 2, py: 0.5 }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 110, flexShrink: 0 }}>
        {label}
      </Typography>
      <Box sx={{ minWidth: 0, wordBreak: 'break-word', typography: 'body2' }}>{children}</Box>
    </Box>
  )
}

function describe(entry: FeedbackDiagnostic): string {
  if (entry.kind === 'api') return `${entry.method ?? ''} ${entry.path ?? ''} → ${entry.status ?? entry.message ?? ''}`
  return [entry.message, entry.source].filter(Boolean).join(' at ')
}

function Screenshot({ feedback }: { feedback: Feedback }) {
  const [zoomed, setZoomed] = useState(false)
  const { data: blob, isError } = useQuery({
    queryKey: [...FEEDBACK_QUERY_KEY, 'screenshot', feedback.id],
    queryFn: () => getFeedbackScreenshot(feedback.id),
    staleTime: Infinity,
  })
  const url = useMemo(() => (blob ? URL.createObjectURL(blob) : null), [blob])
  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url)
  }, [url])

  if (isError) return <Alert severity="warning">The screenshot could not be loaded.</Alert>
  if (!url) return <CircularProgress size={20} />
  return (
    <>
      <ButtonBase
        onClick={() => setZoomed(true)}
        aria-label="Enlarge screenshot"
        sx={{ display: 'block', borderRadius: '8px', overflow: 'hidden', border: 1, borderColor: 'divider', cursor: 'zoom-in' }}
      >
        <Box component="img" src={url} alt="Screenshot sent with the feedback" sx={{ display: 'block', maxWidth: '100%', maxHeight: 360 }} />
      </ButtonBase>
      <Dialog open={zoomed} onClose={() => setZoomed(false)} maxWidth={false}>
        <Box
          component="img"
          src={url}
          alt="Screenshot sent with the feedback, enlarged"
          onClick={() => setZoomed(false)}
          sx={{ display: 'block', maxWidth: '95vw', maxHeight: '92vh', cursor: 'zoom-out' }}
        />
      </Dialog>
    </>
  )
}

export function FeedbackDetail() {
  const { id } = useParams()
  const feedbackId = Number(id)
  const queryClient = useQueryClient()

  const { data: feedback, isLoading, error } = useQuery({
    queryKey: [...FEEDBACK_QUERY_KEY, 'detail', feedbackId],
    queryFn: async () => {
      const result = await getFeedback(feedbackId)
      // A count fetched before this read would otherwise win the race.
      await queryClient.cancelQueries({ queryKey: [...FEEDBACK_QUERY_KEY, 'unread'] })
      void queryClient.invalidateQueries({ queryKey: [...FEEDBACK_QUERY_KEY, 'unread'] })
      void queryClient.invalidateQueries({ queryKey: [...FEEDBACK_QUERY_KEY, 'list'] })
      return result
    },
    enabled: Number.isInteger(feedbackId),
  })

  const resolve = useMutation({
    mutationFn: (resolved: boolean) => setFeedbackResolved(feedbackId, resolved),
    onSuccess: (updated) => {
      queryClient.setQueryData([...FEEDBACK_QUERY_KEY, 'detail', feedbackId], updated)
      void queryClient.invalidateQueries({ queryKey: [...FEEDBACK_QUERY_KEY, 'list'] })
      void queryClient.invalidateQueries({ queryKey: [...FEEDBACK_QUERY_KEY, 'unread'] })
    },
  })

  const back = (
    <Button component={RouterLink} to="/admin/feedback" startIcon={<ArrowBackRoundedIcon />} sx={{ mb: 2 }}>
      All feedback
    </Button>
  )

  if (isLoading) return <CircularProgress />
  if (error || !feedback) {
    return (
      <Box>
        {back}
        <Alert severity="error">{error instanceof Error ? error.message : 'No such feedback.'}</Alert>
      </Box>
    )
  }

  const resolved = Boolean(feedback.resolved_at)
  const reply = `mailto:${feedback.email}?subject=${encodeURIComponent('Re: your Freepod feedback')}`

  return (
    <Box>
      {back}
      <Paper variant="outlined" sx={{ p: 3, borderRadius: '12px' }}>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2, flexWrap: 'wrap' }}>
          <Chip label={TOPIC_LABELS[feedback.topic]} color={feedback.topic === 'bug' ? 'error' : feedback.topic === 'idea' ? 'primary' : 'default'} />
          <Chip label={resolved ? 'Resolved' : 'Open'} variant="outlined" color={resolved ? 'success' : 'default'} />
          <Box sx={{ flex: 1 }} />
          <Button variant="outlined" startIcon={<MailOutlineRoundedIcon />} href={reply}>
            Reply
          </Button>
          <Button variant="contained" disabled={resolve.isPending} onClick={() => resolve.mutate(!resolved)}>
            {resolved ? 'Reopen' : 'Mark resolved'}
          </Button>
        </Stack>
        {resolve.error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {resolve.error.message}
          </Alert>
        )}
        <Typography sx={{ whiteSpace: 'pre-wrap', mb: 3 }}>{feedback.message}</Typography>

        <Field label="From">
          <Link component={RouterLink} to={`/admin/users?q=${encodeURIComponent(feedback.email)}`}>
            {feedback.email}
          </Link>
        </Field>
        <Field label="Sent">{formatLocalIso(feedback.created_at)}</Field>
        <Field label="Page">
          <Link href={feedback.page} target="_blank" rel="noopener noreferrer">
            {feedback.page}
          </Link>
        </Field>
        <Field label="Browser">{feedback.user_agent ?? '—'}</Field>
        <Field label="Viewport">{feedback.viewport ?? '—'}</Field>
        <Field label="UI build">{feedback.ui_build ?? '—'}</Field>
        <Field label="API build">{feedback.api_build ?? '—'}</Field>
        {resolved && (
          <Field label="Resolved">
            {formatLocalIso(feedback.resolved_at)} by {feedback.resolved_by_email ?? `user ${feedback.resolved_by}`}
          </Field>
        )}

        <Typography variant="subtitle2" sx={{ mt: 3, mb: 1 }}>
          Screenshot
        </Typography>
        {feedback.has_screenshot ? <Screenshot feedback={feedback} /> : <Typography variant="body2" color="text.secondary">None</Typography>}

        <Typography variant="subtitle2" sx={{ mt: 3, mb: 1 }}>
          Diagnostics
        </Typography>
        {feedback.diagnostics.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No recent errors
          </Typography>
        ) : (
          <Box component="ol" sx={{ m: 0, pl: 2.5, fontFamily: 'monospace', fontSize: 13 }}>
            {feedback.diagnostics.map((entry, i) => (
              <li key={i}>
                <Box component="span" sx={{ color: 'text.secondary' }}>
                  {entry.at ? formatLocalIso(entry.at) : ''} {entry.kind}
                </Box>{' '}
                <Box component="span" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {describe(entry)}
                </Box>
              </li>
            ))}
          </Box>
        )}
      </Paper>
    </Box>
  )
}
