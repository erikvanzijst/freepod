import type { ReactNode } from 'react'
import { Box, Container, Stack, Typography } from '@mui/material'
import Inventory2RoundedIcon from '@mui/icons-material/Inventory2Rounded'
import LanguageRoundedIcon from '@mui/icons-material/LanguageRounded'
import SwapHorizRoundedIcon from '@mui/icons-material/SwapHorizRounded'
import VisibilityOffRoundedIcon from '@mui/icons-material/VisibilityOffRounded'
import { accent, DISPLAY, fg, line, MONO, SANS } from './landingTokens'
import Reveal from './Reveal'

/** The flag of Europe: twelve gold stars in a circle on blue. */
function EuFlag() {
  const stars = Array.from({ length: 12 }, (_, i) => {
    const a = (i * Math.PI) / 6
    return { x: 15 + 6 * Math.sin(a), y: 10 - 6 * Math.cos(a) }
  })
  return (
    <Box component="svg" viewBox="0 0 30 20" sx={{ width: 26, height: 17, borderRadius: '3px', display: 'block' }}>
      <rect width="30" height="20" fill="#003399" />
      {stars.map((s, i) => (
        <circle key={i} cx={s.x} cy={s.y} r="0.95" fill="#FFCC00" />
      ))}
    </Box>
  )
}

interface Fact {
  icon: ReactNode
  title: string
  body: string
}

const iconSx = { fontSize: 22, color: accent.cyan }

const facts: Fact[] = [
  {
    icon: <Inventory2RoundedIcon sx={iconSx} />,
    title: 'A private pod for every app',
    body: 'Each app runs in a pod of its own, with its own storage, separate from everyone else’s.',
  },
  {
    icon: <LanguageRoundedIcon sx={iconSx} />,
    title: 'Your own address',
    body: 'Claim a name once and your apps live under it, like photos.alex.freepod.eu. Or use a domain you already own.',
  },
  {
    icon: <SwapHorizRoundedIcon sx={iconSx} />,
    title: 'Free to move',
    body: 'Every app is open source and keeps your data in standard formats. Export it whenever you like, or run the same app somewhere else.',
  },
  {
    icon: <EuFlag />,
    title: 'Hosted in the EU',
    body: 'Your pods run on servers in the European Union, under the GDPR.',
  },
  {
    icon: <VisibilityOffRoundedIcon sx={iconSx} />,
    title: 'No ads, no tracking',
    body: 'Subscriptions pay for Freepod. Nothing in your pods is used for advertising or profiling.',
  },
]

/** Why Freepod exists and who it is for, beside what running an app on it means, in plain facts. */
export function PodFacts() {
  return (
    <Box component="section" id="why" sx={{ py: { xs: 9, md: 13 }, scrollMarginTop: 80 }}>
      <Container
        maxWidth="lg"
        sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: { xs: 5, md: 10 }, alignItems: 'start' }}
      >
        <Reveal sx={{ position: { md: 'sticky' }, top: { md: 120 } }}>
          <Typography
            component="h2"
            sx={{ fontFamily: MONO, fontSize: 12.5, letterSpacing: '0.22em', textTransform: 'uppercase', color: accent.cyan, mb: 2.5 }}
          >
            Why we built Freepod
          </Typography>
          <Typography sx={{ fontFamily: DISPLAY, fontWeight: 400, fontSize: { xs: 21, md: 23 }, lineHeight: 1.5, color: fg.primary }}>
            Most of us just want our technology to work and stay out of sight. But where our photos,
            documents and messages end up, and what they're used for, still matters. We built Freepod to
            offer the technology you depend on every day, while respecting your control and privacy, using
            apps and services designed around these principles.{' '}
            <Box component="span" sx={{ color: accent.blue }}>
              And with all our code open source, we have the receipts to prove it.
            </Box>
          </Typography>
          <Typography sx={{ fontFamily: SANS, fontSize: { xs: 16.5, md: 17 }, lineHeight: 1.65, color: fg.muted, mt: 2.5 }}>
            For households, independent shops and growing businesses alike: all the control of having your own
            cloud, with none of the work of running one.
          </Typography>
        </Reveal>

        <Box>
          {facts.map((fact, i) => (
            <Reveal key={fact.title} delay={i * 70}>
              <Stack
                direction="row"
                spacing={2.5}
                sx={{ py: 3, borderTop: `1px solid ${line.soft}`, ...(i === facts.length - 1 && { borderBottom: `1px solid ${line.soft}` }) }}
              >
                <Box sx={{ width: 28, pt: 0.5, display: 'flex', justifyContent: 'center', flex: '0 0 auto' }}>{fact.icon}</Box>
                <Box>
                  <Typography sx={{ fontFamily: SANS, fontWeight: 600, fontSize: 18.5, color: fg.primary }}>{fact.title}</Typography>
                  <Typography sx={{ fontFamily: SANS, fontSize: 16, lineHeight: 1.6, color: fg.muted, mt: 0.75 }}>{fact.body}</Typography>
                </Box>
              </Stack>
            </Reveal>
          ))}
        </Box>
      </Container>
    </Box>
  )
}

export default PodFacts
