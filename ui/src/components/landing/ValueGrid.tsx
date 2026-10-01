import { Box, Container, Stack, Typography } from '@mui/material'
import ShieldRoundedIcon from '@mui/icons-material/ShieldRounded'
import PublicRoundedIcon from '@mui/icons-material/PublicRounded'
import CodeRoundedIcon from '@mui/icons-material/CodeRounded'
import VisibilityOffRoundedIcon from '@mui/icons-material/VisibilityOffRounded'
import LanguageRoundedIcon from '@mui/icons-material/LanguageRounded'
import FlightTakeoffRoundedIcon from '@mui/icons-material/FlightTakeoffRounded'
import type { SvgIconComponent } from '@mui/icons-material'
import { accent, DISPLAY, fg, line, SANS } from './landingTokens'
import SectionHeading from './SectionHeading'
import Reveal from './Reveal'

interface Value {
  icon: SvgIconComponent
  title: string
  body: string
  color: string
}

const values: Value[] = [
  {
    icon: ShieldRoundedIcon,
    title: 'Dedicated, not shared',
    body: 'Your own isolated instance with its own storage — not a row in a giant database the provider can mine.',
    color: accent.blue,
  },
  {
    icon: PublicRoundedIcon,
    title: 'European jurisdiction',
    body: 'Hosted in the EU, under European privacy law — out of reach of foreign surveillance regimes.',
    color: accent.cyan,
  },
  {
    icon: CodeRoundedIcon,
    title: 'Open source',
    body: 'Every app is open-source and auditable. No black boxes, no proprietary lock-in.',
    color: accent.magenta,
  },
  {
    icon: VisibilityOffRoundedIcon,
    title: 'No ads, no tracking',
    body: 'We earn from honest subscriptions, never from your attention or your data. No tracking cookies, no profiling.',
    color: accent.pink,
  },
  {
    icon: LanguageRoundedIcon,
    title: 'Your own domain',
    body: 'Run each app on a domain you own, with automatic HTTPS certificates managed for you.',
    color: accent.blue,
  },
  {
    icon: FlightTakeoffRoundedIcon,
    title: 'Leave anytime',
    body: 'Standard, open formats mean you can export everything and move on whenever you choose. No hostages here.',
    color: accent.cyan,
  },
]

/** Six-up grid of Freepod's core promises. */
export function ValueGrid() {
  return (
    <Box component="section" id="why" sx={{ py: { xs: 9, md: 14 }, scrollMarginTop: 80 }}>
      <Container maxWidth="lg">
        <SectionHeading
          eyebrow="What you get"
          title={
            <>
              Built around a single idea:
              <br />
              your data belongs to you.
            </>
          }
        />

        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', md: '1fr 1fr 1fr' },
            gap: 0,
            mt: { xs: 6, md: 8 },
            border: `1px solid ${line.soft}`,
            borderRadius: 4,
            overflow: 'hidden',
          }}
        >
          {values.map((value, i) => {
            const Icon = value.icon
            return (
              <Reveal key={value.title} delay={(i % 3) * 80}>
                <Box
                  sx={{
                    height: '100%',
                    p: { xs: 3, md: 4 },
                    borderRight: { md: (i + 1) % 3 === 0 ? 'none' : `1px solid ${line.soft}` },
                    borderBottom: `1px solid ${line.soft}`,
                    transition: 'background 0.25s',
                    '&:hover': { background: 'rgba(255,255,255,0.025)' },
                  }}
                >
                  <Stack
                    sx={{
                      width: 44,
                      height: 44,
                      borderRadius: 2,
                      alignItems: 'center',
                      justifyContent: 'center',
                      background: `${value.color}1f`,
                      border: `1px solid ${value.color}3a`,
                    }}
                  >
                    <Icon sx={{ fontSize: 22, color: value.color }} />
                  </Stack>
                  <Typography
                    sx={{
                      fontFamily: DISPLAY,
                      fontWeight: 600,
                      fontSize: 20,
                      color: fg.primary,
                      mt: 2.5,
                    }}
                  >
                    {value.title}
                  </Typography>
                  <Typography
                    sx={{
                      fontFamily: SANS,
                      fontSize: 15,
                      lineHeight: 1.6,
                      color: fg.muted,
                      mt: 1.25,
                    }}
                  >
                    {value.body}
                  </Typography>
                </Box>
              </Reveal>
            )
          })}
        </Box>
      </Container>
    </Box>
  )
}

export default ValueGrid
