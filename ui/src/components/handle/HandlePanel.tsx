import { Alert, Box, Card, CircularProgress, Stack, Typography } from '@mui/material'
import { CopyButton } from '../CopyButton'
import { fg, line, MONO } from '../landing/landingTokens'
import { useMyHandle } from './useMyHandle'

export function HandlePanel() {
  const handleQuery = useMyHandle()

  if (handleQuery.isLoading) {
    return (
      <Card sx={{ p: 4, display: 'grid', placeItems: 'center' }}>
        <CircularProgress size={22} />
      </Card>
    )
  }

  const held = handleQuery.data
  const handle = held?.handle ?? null
  const suffix = held?.suffix ?? null

  return (
    <Card sx={{ p: 3 }}>
      <Stack spacing={2}>
        <Box>
          <Typography variant="h6">Your handle</Typography>
          <Typography color="text.secondary" sx={{ fontSize: 14 }}>
            Every app you deploy gets a hostname ending in this handle.
          </Typography>
        </Box>

        {handle && suffix ? (
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
              <Box sx={{ flex: 1 }}>{handle}</Box>
              <CopyButton value={handle} label="handle" />
            </Stack>
            <Typography color="text.secondary" sx={{ fontSize: 13 }}>
              Your apps are addressed as{' '}
              <Box component="span" sx={{ fontFamily: MONO, color: fg.primary }}>
                &lt;app&gt;{suffix}
              </Box>
              . Chosen once and kept: a handle cannot be changed or released, because every
              link to your apps outlives the change.
            </Typography>
          </>
        ) : (
          <Alert severity="info" sx={{ borderRadius: '11px' }}>
            You haven't chosen a handle yet. You'll be asked for one on the dashboard, or the
            first time you deploy.
          </Alert>
        )}
      </Stack>
    </Card>
  )
}
