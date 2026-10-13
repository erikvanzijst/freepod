import { useState } from 'react'
import { Box, Button, Collapse, Stack, Typography } from '@mui/material'
import OpenInNewRounded from '@mui/icons-material/OpenInNewRounded'
import ErrorOutlineRounded from '@mui/icons-material/ErrorOutlineRounded'
import CreditCardOffRounded from '@mui/icons-material/CreditCardOffRounded'
import type { Deployment } from '../../api/types'
import { fg, MONO } from '../landing/landingTokens'
import { SUPPORT_EMAIL } from '../../content/contact'
import { toneColor, type DeploymentProblem, type DeploymentView } from './deploymentView'

export interface DeploymentCardProps {
  deployment: Deployment
  userId: number
  deletePending: boolean
  onEdit: (deployment: Deployment) => void
  onDelete: (deployment: Deployment) => void
}

/** Opens the app in a new tab; disabled until it can be reached. */
export function OpenButton({ view, label = 'Open', fullWidth = false }: { view: DeploymentView; label?: string; fullWidth?: boolean }) {
  return (
    <Button
      variant="contained"
      fullWidth={fullWidth}
      disabled={!view.openable}
      href={view.url ?? ''}
      target="_blank"
      rel="noreferrer"
      endIcon={<OpenInNewRounded sx={{ fontSize: '18px !important' }} />}
      sx={{ flex: '0 0 auto' }}
    >
      {label}
    </Button>
  )
}

/** A colored dot and the status in words; the dot pulses while something is happening. */
export function StatusLine({ view, size = 14 }: { view: DeploymentView; size?: number }) {
  const color = toneColor[view.status.tone]
  return (
    <Stack direction="row" alignItems="center" spacing={0.85} sx={{ minWidth: 0 }}>
      <Box
        component="span"
        sx={{
          flex: '0 0 auto',
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: color,
          boxShadow: `0 0 0 3px ${color}26`,
          animation: view.status.progress ? 'dpPulse 1.4s ease-in-out infinite' : 'none',
          '@keyframes dpPulse': { '0%, 100%': { opacity: 1 }, '50%': { opacity: 0.35 } },
        }}
      />
      <Typography noWrap sx={{ fontSize: size, color: view.status.tone === 'ok' ? fg.muted : color, fontWeight: 500 }}>
        {view.status.label}
      </Typography>
    </Stack>
  )
}

const linkSx = {
  p: 0,
  border: 0,
  background: 'none',
  color: fg.faint,
  fontSize: 12.5,
  cursor: 'pointer',
  textDecoration: 'underline',
  '&:hover': { color: fg.primary },
} as const

/** A problem in plain words, with the raw error tucked away for support. */
export function ProblemNotice({ problem, compact = false }: { problem: DeploymentProblem; compact?: boolean }) {
  const [details, setDetails] = useState(false)
  const payment = problem.title === 'Payment failed'
  const color = payment ? toneColor.waiting : toneColor.problem
  return (
    <Box sx={{ p: compact ? 1.5 : 2, borderRadius: '10px', background: `${color}14`, border: `1px solid ${color}40` }}>
      <Stack direction="row" spacing={1.25} alignItems="flex-start">
        {payment ? <CreditCardOffRounded sx={{ fontSize: 19, color, mt: 0.15 }} /> : <ErrorOutlineRounded sx={{ fontSize: 19, color, mt: 0.15 }} />}
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography sx={{ fontWeight: 600, fontSize: 14.5 }}>{problem.title}</Typography>
          <Typography sx={{ fontSize: 13.5, color: fg.muted, lineHeight: 1.5 }}>{problem.message}</Typography>
          {(problem.support || problem.details) && (
            <Stack direction="row" spacing={2} sx={{ mt: 0.75 }}>
              {problem.support && (
                <Box component="a" href={problem.support} sx={{ ...linkSx, color: fg.muted }}>
                  Email {SUPPORT_EMAIL}
                </Box>
              )}
              {problem.details && (
                <Box component="button" onClick={() => setDetails((v) => !v)} aria-expanded={details} sx={linkSx}>
                  {details ? 'Hide details' : 'Show details'}
                </Box>
              )}
            </Stack>
          )}
          {problem.details && (
            <Collapse in={details}>
              <Typography sx={{ mt: 1, fontFamily: MONO, fontSize: 11.5, color: fg.faint, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {problem.details}
              </Typography>
            </Collapse>
          )}
        </Box>
      </Stack>
    </Box>
  )
}
