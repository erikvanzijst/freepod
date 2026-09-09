import { Alert, Box, Card, CircularProgress, Stack, Typography } from '@mui/material'
import { CopyButton } from '../CopyButton'
import { fg, line, MONO } from '../landing/landingTokens'
import { useMySubdomain } from './useMySubdomain'

export function SubdomainPanel() {
  const subdomainQuery = useMySubdomain()

  if (subdomainQuery.isLoading) {
    return (
      <Card sx={{ p: 4, display: 'grid', placeItems: 'center' }}>
        <CircularProgress size={22} />
      </Card>
    )
  }

  const held = subdomainQuery.data
  const fqdn = held?.fqdn ?? null

  return (
    <Card sx={{ p: 3 }}>
      <Stack spacing={2}>
        <Box>
          <Typography variant="h6">Your domain name</Typography>
          <Typography color="text.secondary" sx={{ fontSize: 14 }}>
            Every application you deploy sits underneath this domain name.
          </Typography>
        </Box>

        {fqdn ? (
          <>
            <Stack
              direction="row"
              spacing={1}
              alignItems="center"
              sx={{
                fontFamily: MONO,
                fontSize: 17,
                color: fg.primary,
                border: `1px solid ${line.soft}`,
                borderRadius: '12px',
                px: 2,
                py: 1.5,
                background: 'rgba(7,10,20,0.35)',
                wordBreak: 'break-all',
              }}
            >
              <Box sx={{ flex: 1 }}>{fqdn}</Box>
              <CopyButton value={fqdn} label="domain name" />
            </Stack>
            <Typography color="text.secondary" sx={{ fontSize: 13 }}>
              Chosen once and kept: a domain name cannot be changed or released, because
              everything issued against it — links, certificates, other people's DNS caches
              — outlives the change.
            </Typography>
          </>
        ) : (
          <Alert severity="info" sx={{ borderRadius: '11px' }}>
            You haven't claimed a domain name yet. You'll be asked for one on the dashboard, or
            the first time you deploy.
          </Alert>
        )}
      </Stack>
    </Card>
  )
}
