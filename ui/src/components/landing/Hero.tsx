import { Box, Button, Container, Stack, Typography } from '@mui/material'
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded'
import { Link as RouterLink } from 'react-router-dom'
import { accent, DISPLAY, fg, MONO, primaryButtonSx, SANS } from './landingTokens'
import AuroraBackground from './AuroraBackground'
import PodPreview from './PodPreview'

const facts = ['Hosted in the EU', 'Open-source apps', 'No ads or tracking']

/** Build-up: staggered fade for the hero stack on first paint. */
const reveal = (i: number) => ({
  opacity: 0,
  animation: 'lp-fade-up 0.85s cubic-bezier(0.22,1,0.36,1) forwards',
  animationDelay: `${0.1 + i * 0.12}s`,
})

export function Hero() {
  return (
    <Box component="section" sx={{ position: 'relative', overflow: 'hidden' }}>
      <AuroraBackground />

      <Container
        maxWidth="lg"
        sx={{
          position: 'relative',
          zIndex: 1,
          pt: { xs: 8, md: 13 },
          pb: { xs: 9, md: 14 },
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: '3fr 2fr' },
          gap: { xs: 7, md: 8 },
          alignItems: 'center',
        }}
      >
        <Box>
          <Typography
            component="p"
            sx={{
              ...reveal(0),
              fontFamily: MONO,
              fontSize: 13,
              letterSpacing: '0.2em',
              textTransform: 'uppercase',
              color: accent.cyan,
              mb: 3,
            }}
          >
            Your own private cloud
          </Typography>

          <Typography
            component="h1"
            sx={{
              ...reveal(1),
              fontFamily: DISPLAY,
              fontWeight: 500,
              color: fg.primary,
              fontSize: { xs: 40, sm: 50, md: 52, lg: 58 },
              lineHeight: 1.03,
              letterSpacing: '-0.025em',
            }}
          >
            Your digital life,{' '}
            <Box component="span" sx={{ display: { sm: 'block' } }}>
              in a cloud{' '}
              <Box
                component="em"
                sx={{
                  fontStyle: 'italic',
                  pr: '0.04em',
                  backgroundImage: `linear-gradient(120deg, ${accent.blue}, ${accent.pink})`,
                  WebkitBackgroundClip: 'text',
                  backgroundClip: 'text',
                  color: 'transparent',
                }}
              >
                you
              </Box>{' '}
              control.
            </Box>
          </Typography>

          <Typography
            sx={{
              ...reveal(2),
              fontFamily: SANS,
              color: fg.muted,
              fontSize: { xs: 17, md: 19 },
              lineHeight: 1.6,
              maxWidth: 600,
              mt: 3.5,
            }}
          >
            Freepod gives you private alternatives to the cloud services you use every day, for your photos,
            files, passwords and chats. Each app runs in a pod of its own, under your own name, hosted in the EU.
            And your data is always yours to take with you.
          </Typography>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ ...reveal(3), mt: 5 }}>
            <Button component={RouterLink} to="/apps" endIcon={<ArrowForwardRoundedIcon />} sx={primaryButtonSx}>
              Browse the apps
            </Button>
          </Stack>

          <Stack direction="row" flexWrap="wrap" useFlexGap spacing={2.5} sx={{ ...reveal(4), mt: 4 }}>
            {facts.map((fact) => (
              <Stack key={fact} direction="row" alignItems="center" spacing={1}>
                <Box sx={{ width: 5, height: 5, borderRadius: '50%', background: accent.cyan }} />
                <Typography sx={{ fontFamily: SANS, fontSize: 14.5, color: fg.muted }}>{fact}</Typography>
              </Stack>
            ))}
          </Stack>
        </Box>

        <Box sx={reveal(3)}>
          <PodPreview />
        </Box>
      </Container>
    </Box>
  )
}

export default Hero
