import { useMemo, useState } from 'react'
import { Alert, Box, Button, Stack, Typography } from '@mui/material'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import PublicIcon from '@mui/icons-material/Public'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { claimSubdomain } from '../../api/endpoints'
import { DISPLAY, fg, line, MONO } from '../landing/landingTokens'
import { SubdomainField, type SubdomainStatus } from './SubdomainField'
import { claimReasonText } from './subdomainReasons'

/** Everything on this screen is one measure wide, whatever container holds it. */
const MEASURE = 520

/** The email local part, reduced to something that could be a DNS label. */
export function labelFromEmail(email: string): string {
  return email.split('@')[0].toLowerCase().replace(/[^a-z0-9-]/g, '').replace(/^-+|-+$/g, '').slice(0, 63)
}

interface ClaimSubdomainProps {
  /** The platform domain, e.g. `freepod.eu`. */
  domain: string
  email: string
  /** "Not now": closes the modal, or collapses the dashboard section to a banner. */
  onDismiss: () => void
  /** Called once the domain name is held, so a deploy the claim interrupted can go on. */
  onClaimed?: (subdomain: string) => void
  /** Focus and select the prefill. Right when a modal opens; not on page load. */
  autoSelect?: boolean
  /**
   * Which question is being asked.
   *
   * On the dashboard the user is choosing the account's own domain name with no
   * application in mind, so no application label is shown — the odometer would
   * be answering a question nobody has asked yet. On the deploy path they are
   * one step from creating an instance, and the whole hostname is the thing to
   * show.
   */
  context?: 'account' | 'deploy'
}

/**
 * On the dashboard the claim is the page's one task, so it is centred and the
 * domain name is its focal point. In the deploy modal it is a form the user opened
 * on the way to something else, and reads left-aligned like one.
 */

export function ClaimSubdomain({
  domain,
  email,
  onDismiss,
  onClaimed,
  autoSelect = false,
  context = 'deploy',
}: ClaimSubdomainProps) {
  const queryClient = useQueryClient()
  const [label, setLabel] = useState(() => labelFromEmail(email))
  const [status, setStatus] = useState<SubdomainStatus>({ status: 'empty' })
  const [confirming, setConfirming] = useState(false)
  const [claimError, setClaimError] = useState<string | null>(null)

  const deploying = context === 'deploy'
  const centred = !deploying
  const align = centred ? 'center' : 'flex-start'

  const claim = useMutation({
    mutationFn: () => claimSubdomain(label.trim().toLowerCase()),
    onSuccess: (held) => {
      queryClient.invalidateQueries({ queryKey: ['my-subdomain'] })
      onClaimed?.(held.subdomain ?? label)
      onDismiss()
    },
    onError: (error: unknown) => {
      // The claim races other claims: two accounts can be told the same label is
      // free. The unique index decides, and the loser lands back here.
      const code = error instanceof ApiError ? error.code : undefined
      setClaimError(
        code === 'subdomain_taken'
          ? claimReasonText('claimed')
          : error instanceof Error
            ? error.message
            : 'The domain could not be claimed.',
      )
      setConfirming(false)
    },
  })

  const canClaim = status.status === 'available' && !claim.isPending
  const fqdn = useMemo(() => `${label.trim().toLowerCase()}.${domain}`, [label, domain])

  const handleDismiss = () => {
    setConfirming(false)
    setClaimError(null)
    onDismiss()
  }

  const eyebrow = (text: string) => (
    <Typography
      sx={{
        fontFamily: MONO,
        fontSize: 10.5,
        letterSpacing: '0.2em',
        textTransform: 'uppercase',
        color: 'primary.main',
        mb: 1.5,
      }}
    >
      {text}
    </Typography>
  )

  const heading = (text: string) => (
    <Typography sx={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 27, letterSpacing: '-0.02em', mb: 1.25 }}>
      {text}
    </Typography>
  )

  if (confirming) {
    return (
      <Box sx={{ maxWidth: MEASURE, mx: centred ? 'auto' : 0, textAlign: centred ? 'center' : 'left' }}>
        {eyebrow('Confirm')}
        {heading('This is yours from now on')}

        <Box
          sx={{
            fontFamily: MONO,
            fontSize: { xs: 17, sm: 24 },
            textAlign: 'center',
            py: 3.25,
            px: 1.5,
            my: 1,
            border: `1px dashed ${line.soft}`,
            borderRadius: '14px',
            background: 'rgba(7,10,20,0.5)',
            wordBreak: 'break-all',
            color: fg.primary,
          }}
        >
          {fqdn}
        </Box>

        <Alert
          icon={<WarningAmberIcon fontSize="inherit" />}
          severity="warning"
          sx={{ mt: 1.5, mb: 2.75, borderRadius: '11px' }}
        >
          Your home domain name can't be changed or released. Support can't move one for you later.
        </Alert>

        <Stack direction="row" spacing={1.25} justifyContent={deploying ? 'flex-end' : 'center'}>
          <Button variant="outlined" color="inherit" onClick={() => setConfirming(false)}>
            Go back
          </Button>
          <Button variant="contained" onClick={() => claim.mutate()} disabled={claim.isPending}>
            Yes, claim it
          </Button>
        </Stack>
      </Box>
    )
  }

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: align,
        textAlign: centred ? 'center' : 'left',
        maxWidth: centred ? 'none' : MEASURE,
        mx: 'auto',
      }}
    >
      {eyebrow('Your domain')}
      {heading('Claim your free domain')}
      <Typography sx={{ fontSize: 14.5, color: 'text.secondary', mb: 3, maxWidth: '54ch' }}>
        {deploying
          ? 'Your application will then get a name underneath this personal subdomain name.'
          : 'Your own corner of Freepod. It will be the home for all your applications and nobody else can use it.'}
      </Typography>

      <SubdomainField
        value={label}
        onChange={(next) => {
          setClaimError(null)
          setLabel(next)
        }}
        domain={domain}
        onStatusChange={setStatus}
        autoSelect={autoSelect}
        disabled={claim.isPending}
        showReel={deploying}
        align={centred ? 'center' : 'start'}
      />

      {claimError && (
        <Alert severity="error" sx={{ mt: 2, borderRadius: '11px', maxWidth: MEASURE }}>
          {claimError}
        </Alert>
      )}

      <Stack
        component="ul"
        direction={centred ? { xs: 'column', sm: 'row' } : 'column'}
        spacing={centred ? { xs: 1.125, sm: 4 } : 1.125}
        sx={{
          listStyle: 'none',
          p: 0,
          my: 2.75,
          textAlign: 'left',
          maxWidth: centred ? 760 : 'none',
        }}
      >
        <Stack component="li" direction="row" spacing={1.25} alignItems="flex-start" sx={{ flex: 1 }}>
          <ErrorOutlineIcon sx={{ fontSize: 17, color: fg.faint, mt: 0.4 }} />
          <Typography sx={{ fontSize: 13.5, color: 'text.secondary' }}>
            <strong>It's permanent.</strong> Apps, links and certificates are all issued
            against it, so it can't be changed later.
          </Typography>
        </Stack>
        <Stack component="li" direction="row" spacing={1.25} alignItems="flex-start" sx={{ flex: 1 }}>
          <PublicIcon sx={{ fontSize: 17, color: fg.faint, mt: 0.4 }} />
          <Typography sx={{ fontSize: 13.5, color: 'text.secondary' }}>
            <strong>It's public.</strong> It appears in your app addresses and in public
            certificate logs, so pick something you're happy being seen.
          </Typography>
        </Stack>
      </Stack>

      <Stack direction="row" spacing={1.25} justifyContent={deploying ? 'flex-end' : 'center'}>
        <Button variant="text" color="inherit" onClick={handleDismiss}>
          Not now
        </Button>
        <Button variant="contained" onClick={() => setConfirming(true)} disabled={!canClaim}>
          Claim this name
        </Button>
      </Stack>
    </Box>
  )
}
