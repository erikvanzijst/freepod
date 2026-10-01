import { Box, Button, Container, Typography } from '@mui/material'
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded'
import { Link as RouterLink } from 'react-router-dom'
import { accent, cardSurface, DISPLAY, fg, MONO, SANS } from './landingTokens'
import Reveal from './Reveal'
import CodeBlock from './dev/CodeBlock'

const snippet = [
  {
    label: 'Terminal',
    lang: 'shell' as const,
    code: `$ freepod init
$ freepod deploy
https://myapp.ada.freepod.eu`,
  },
]

/** Points developers from the consumer landing page to /dev. */
export function DevelopersBand() {
  return (
    <Box component="section" id="developers" sx={{ py: { xs: 6, md: 10 }, scrollMarginTop: 80 }}>
      <Container maxWidth="lg">
        <Reveal>
          <Box
            sx={{
              p: { xs: 3, md: 6 },
              borderRadius: 5,
              ...cardSurface,
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', md: '6fr 5fr' },
              gap: { xs: 4, md: 6 },
              alignItems: 'center',
            }}
          >
            <Box>
              <Typography
                sx={{ fontFamily: MONO, fontSize: 12.5, letterSpacing: '0.22em', textTransform: 'uppercase', color: accent.cyan, mb: 2 }}
              >
                For developers
              </Typography>
              <Typography
                component="h2"
                sx={{ fontFamily: DISPLAY, fontWeight: 500, fontSize: { xs: 30, md: 40 }, lineHeight: 1.1, letterSpacing: '-0.02em', color: fg.primary }}
              >
                Bring your own app.
              </Typography>
              <Typography sx={{ fontFamily: SANS, fontSize: { xs: 16, md: 17 }, lineHeight: 1.65, color: fg.muted, mt: 2, maxWidth: 520 }}>
                Can't find the app you need? Build it yourself, or have your coding agent build it, and
                deploy it with one command. Postgres, object storage and sign-in are built in.
              </Typography>
              <Button
                component={RouterLink}
                to="/dev"
                endIcon={<ArrowForwardRoundedIcon />}
                sx={{
                  mt: 3.5,
                  borderRadius: 999,
                  px: 3,
                  py: 1.25,
                  fontSize: 16,
                  fontWeight: 600,
                  color: fg.primary,
                  border: '1px solid rgba(255,255,255,0.18)',
                  background: 'rgba(255,255,255,0.03)',
                  '&:hover': { background: 'rgba(255,255,255,0.08)', borderColor: 'rgba(255,255,255,0.3)' },
                }}
              >
                Freepod for developers
              </Button>
            </Box>
            <CodeBlock snippets={snippet} />
          </Box>
        </Reveal>
      </Container>
    </Box>
  )
}

export default DevelopersBand
