import { Box, Button, Container, Stack, Typography } from '@mui/material'
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded'
import { Link as RouterLink } from 'react-router-dom'
import AuroraBackground from './AuroraBackground'
import Reveal from './Reveal'
import { DISPLAY, fg, line, primaryButtonSx, SANS, secondaryButtonSx } from './landingTokens'

interface CtaBandProps {
  onSignup: () => void
}

/** Closing invitation before the footer. */
export function CtaBand({ onSignup }: CtaBandProps) {
  return (
    <Box component="section" sx={{ py: { xs: 4, md: 7 } }}>
      <Container maxWidth="lg">
        <Reveal>
          <Box
            sx={{
              position: 'relative',
              overflow: 'hidden',
              borderRadius: '12px',
              border: `1px solid ${line.soft}`,
              px: { xs: 3, md: 5 },
              py: { xs: 4, md: 4.5 },
            }}
          >
            <AuroraBackground subtle />
            <Stack
              direction={{ xs: 'column', md: 'row' }}
              alignItems={{ xs: 'flex-start', md: 'center' }}
              justifyContent="space-between"
              spacing={3}
              sx={{ position: 'relative', zIndex: 1 }}
            >
              <Box>
                <Typography component="h2" sx={{ fontFamily: DISPLAY, fontWeight: 500, fontSize: { xs: 28, md: 32 }, lineHeight: 1.15 }}>
                  Start your pod today.
                </Typography>
                <Typography sx={{ fontFamily: SANS, color: fg.muted, fontSize: 16.5, lineHeight: 1.6, mt: 0.75 }}>
                  Claim your name, pick your first app, and open it as soon as it's ready.
                </Typography>
              </Box>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ flex: '0 0 auto', width: { xs: '100%', sm: 'auto' } }}>
                <Button onClick={onSignup} endIcon={<ArrowForwardRoundedIcon />} sx={primaryButtonSx}>
                  Create your account
                </Button>
                <Button component={RouterLink} to="/apps" sx={secondaryButtonSx}>
                  Browse the apps
                </Button>
              </Stack>
            </Stack>
          </Box>
        </Reveal>
      </Container>
    </Box>
  )
}

export default CtaBand
