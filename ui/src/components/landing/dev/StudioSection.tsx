import { Box, Button, Container, Stack, Typography } from '@mui/material'
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded'
import { Link as RouterLink } from 'react-router-dom'
import { accent, DISPLAY, fg, MONO, SANS } from '../landingTokens'
import Reveal from '../Reveal'
import SectionAnchor from '../SectionAnchor'
import StudioPlayer from './StudioPlayer'
import { sectionPy } from './layout'

const points: [string, string][] = [
  ['Watch it take shape', 'Click through your app in a live preview while the agent builds it.'],
  ['Deploy when it works', 'One more prompt, and it runs on its own address with a database if it needs one.'],
  ['Free models included', 'Or bring the API key of the AI plan you already have.'],
  ['The code is still yours', 'GitHub integration, a terminal and root access are a click away if you want to take over.'],
]

/**
 * App Studio, Freepod's in-browser coding agent, pitched for what it is best
 * at: quick prototypes and small personal apps, without opening an editor.
 */
export function StudioSection() {
  return (
    <Box component="section" id="app-studio" sx={{ py: sectionPy, scrollMarginTop: 80 }}>
      <Container maxWidth="lg">
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: '7fr 5fr' },
            gap: { xs: 5, md: 7 },
            alignItems: 'start',
          }}
        >
          <Reveal sx={{ order: { xs: 2, md: 1 }, pt: { xs: 6, md: 0 } }}>
            <StudioPlayer />
          </Reveal>

          <Box sx={{ order: { xs: 1, md: 2 } }}>
            <Typography
              sx={{ fontFamily: MONO, fontSize: 12.5, letterSpacing: '0.22em', textTransform: 'uppercase', color: accent.cyan, mb: 2 }}
            >
              App Studio
            </Typography>
            <Typography
              component="h2"
              sx={{
                fontFamily: DISPLAY,
                fontWeight: 500,
                fontSize: { xs: 32, md: 40 },
                lineHeight: 1.1,
                letterSpacing: '-0.02em',
                color: fg.primary,
              }}
            >
              <SectionAnchor id="app-studio" label="App Studio" />
              From idea to app, in your browser.
            </Typography>
            <Typography sx={{ fontFamily: SANS, fontSize: 17, lineHeight: 1.65, color: fg.muted, mt: 2 }}>
              A game for the kids, a tracker for your running club, a prototype to show on Monday. App Studio is
              Freepod&rsquo;s own coding agent: describe the app, play with it, ask for changes, deploy. No
              editor, laptop, or tools needed.
            </Typography>

            <Stack component="ul" spacing={1.75} sx={{ listStyle: 'none', p: 0, m: 0, mt: 3.5 }}>
              {points.map(([title, body]) => (
                <Stack component="li" key={title} direction="row" spacing={1.5} alignItems="baseline">
                  <Box
                    aria-hidden
                    sx={{ flexShrink: 0, width: 6, height: 6, borderRadius: '50%', background: accent.cyan, transform: 'translateY(-2px)' }}
                  />
                  <Typography sx={{ fontFamily: SANS, fontSize: 15.5, lineHeight: 1.55, color: fg.faint }}>
                    <Box component="span" sx={{ color: fg.primary, fontWeight: 600 }}>
                      {title}.
                    </Box>{' '}
                    {body}
                  </Typography>
                </Stack>
              ))}
            </Stack>

            <Button
              component={RouterLink}
              to="/apps/appstudio"
              endIcon={<ArrowForwardRoundedIcon />}
              sx={{
                mt: 4,
                borderRadius: 999,
                px: 3,
                py: 1.2,
                fontSize: 16,
                fontWeight: 600,
                color: fg.primary,
                border: '1px solid rgba(255,255,255,0.18)',
                background: 'rgba(255,255,255,0.03)',
                '&:hover': { background: 'rgba(255,255,255,0.08)', borderColor: 'rgba(255,255,255,0.3)' },
              }}
            >
              Try App Studio
            </Button>
          </Box>
        </Box>
      </Container>
    </Box>
  )
}

export default StudioSection
