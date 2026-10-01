import { useState } from 'react'
import { Box, Button, Chip, Container, Stack, Typography } from '@mui/material'
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded'
import { Link as RouterLink } from 'react-router-dom'
import { accent, DISPLAY, fg, line, MONO, SANS } from '../landingTokens'
import AuroraBackground from '../AuroraBackground'
import { CopyButton } from '../../CopyButton'
import { REPO_URL } from '../../RepoLink'
import { useAuth } from '../../../state/AuthContext'

export const CLI_DOCS_URL = `${REPO_URL}/tree/master/cli#readme`

const installers = [
  { label: 'uv', command: 'uv tool install freepod' },
  { label: 'brew', command: 'brew install erikvanzijst/tap/freepod' },
  { label: 'pip', command: 'pip install freepod' },
]

const trustPoints = ['EU-hosted', 'Open source', 'Bring your own domain']

const reveal = (i: number) => ({
  opacity: 0,
  animation: 'lp-fade-up 0.85s cubic-bezier(0.22,1,0.36,1) forwards',
  animationDelay: `${0.1 + i * 0.12}s`,
})

const primaryButtonSx = {
  borderRadius: 999,
  px: 4,
  py: 1.5,
  fontSize: 17,
  fontWeight: 600,
  color: '#fff',
  background: 'linear-gradient(120deg, #2563EB, #7C5BFF 55%, #EC4899)',
  boxShadow: '0 14px 40px rgba(124,91,255,0.4)',
  transition: 'transform 0.2s, box-shadow 0.2s',
  '&:hover': {
    transform: 'translateY(-2px)',
    boxShadow: '0 18px 48px rgba(124,91,255,0.5)',
    background: 'linear-gradient(120deg, #1d4fd0, #6d4bf0 55%, #db3b89)',
  },
}

function InstallCommand() {
  const [active, setActive] = useState(installers[0].label)
  const current = installers.find((i) => i.label === active) ?? installers[0]

  return (
    <Box
      sx={{
        mx: 'auto',
        maxWidth: 520,
        textAlign: 'left',
        borderRadius: '12px',
        border: '1px solid rgba(255,255,255,0.1)',
        background: 'rgba(7, 10, 20, 0.7)',
        backdropFilter: 'blur(10px)',
        boxShadow: '0 24px 60px rgba(3, 6, 16, 0.5)',
        overflow: 'hidden',
      }}
    >
      <Stack direction="row" role="tablist" sx={{ px: 1, borderBottom: `1px solid ${line.soft}` }}>
        {installers.map(({ label }) => {
          const selected = label === active
          return (
            <Box
              key={label}
              component="button"
              role="tab"
              aria-selected={selected}
              onClick={() => setActive(label)}
              sx={{
                all: 'unset',
                cursor: 'pointer',
                px: 1.5,
                py: 1,
                fontFamily: MONO,
                fontSize: 12.5,
                color: selected ? fg.primary : fg.faint,
                boxShadow: selected ? `inset 0 -2px 0 ${accent.blue}` : 'none',
                '&:hover': { color: fg.primary },
                '&:focus-visible': { outline: `2px solid ${accent.blue}`, outlineOffset: -2 },
              }}
            >
              {label}
            </Box>
          )
        })}
      </Stack>
      <Stack direction="row" alignItems="center" sx={{ pl: 2.5, pr: 1, py: 1.25 }}>
        <Box sx={{ flex: 1, minWidth: 0, fontFamily: MONO, fontSize: { xs: 14, sm: 16 }, whiteSpace: 'nowrap', overflowX: 'auto' }}>
          <Box component="span" sx={{ color: fg.faint }}>$ </Box>
          <Box component="span" sx={{ color: fg.primary }}>{current.command}</Box>
        </Box>
        <Box sx={{ color: fg.faint, '& button': { color: 'inherit' } }}>
          <CopyButton value={current.command} label="install command" />
        </Box>
      </Stack>
    </Box>
  )
}

export function DevHero({ onSignup }: { onSignup: () => void }) {
  const { user } = useAuth()

  return (
    <Box component="section" sx={{ position: 'relative', overflow: 'hidden' }}>
      <AuroraBackground />
      <Container
        maxWidth="md"
        sx={{ position: 'relative', zIndex: 1, textAlign: 'center', pt: { xs: 9, md: 13 }, pb: { xs: 6, md: 8 } }}
      >
        <Box sx={reveal(0)}>
          <Typography
            component="p"
            sx={{ fontFamily: MONO, fontSize: 13, letterSpacing: '0.22em', textTransform: 'uppercase', color: accent.cyan, mb: 3 }}
          >
            Freepod for developers
          </Typography>
        </Box>

        <Box sx={reveal(1)}>
          <Typography
            component="h1"
            sx={{
              fontFamily: DISPLAY,
              fontWeight: 500,
              color: fg.primary,
              fontSize: { xs: 44, sm: 60, md: 76 },
              lineHeight: 1.03,
              letterSpacing: '-0.025em',
            }}
          >
            Your code, live
            <br />
            {' '}
            <Box
              component="em"
              sx={{
                fontStyle: 'italic',
                backgroundImage: `linear-gradient(120deg, ${accent.blue}, ${accent.pink})`,
                WebkitBackgroundClip: 'text',
                backgroundClip: 'text',
                color: 'transparent',
                pr: '0.06em',
              }}
            >
              in one command.
            </Box>
          </Typography>
        </Box>

        <Box sx={reveal(2)}>
          <Typography
            sx={{ fontFamily: SANS, color: fg.muted, fontSize: { xs: 17, md: 20 }, lineHeight: 1.6, maxWidth: 640, mx: 'auto', mt: 3.5 }}
          >
            Build and ship code, with or without an agent. Your stack, your
            database, your domain, hosted in Europe.
          </Typography>
        </Box>

        <Box sx={{ ...reveal(3), mt: 5 }}>
          <InstallCommand />
        </Box>

        <Box sx={reveal(4)}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} justifyContent="center" sx={{ mt: 4 }}>
            {user ? (
              <Button component={RouterLink} to="/" endIcon={<ArrowForwardRoundedIcon />} sx={primaryButtonSx}>
                Open your dashboard
              </Button>
            ) : (
              <Button onClick={onSignup} endIcon={<ArrowForwardRoundedIcon />} sx={primaryButtonSx}>
                Create your account
              </Button>
            )}
            <Button
              href={CLI_DOCS_URL}
              target="_blank"
              rel="noopener noreferrer"
              sx={{
                borderRadius: 999,
                px: 3.5,
                py: 1.5,
                fontSize: 17,
                fontWeight: 600,
                color: fg.primary,
                border: '1px solid rgba(255,255,255,0.18)',
                background: 'rgba(255,255,255,0.03)',
                '&:hover': { background: 'rgba(255,255,255,0.08)', borderColor: 'rgba(255,255,255,0.3)' },
              }}
            >
              Read the docs
            </Button>
          </Stack>
        </Box>

        <Box sx={reveal(5)}>
          <Stack direction="row" flexWrap="wrap" justifyContent="center" spacing={1.25} useFlexGap sx={{ mt: 5 }}>
            {trustPoints.map((point) => (
              <Chip
                key={point}
                label={point}
                size="small"
                sx={{
                  fontFamily: SANS,
                  color: fg.muted,
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  px: 0.5,
                }}
              />
            ))}
          </Stack>
        </Box>
      </Container>
    </Box>
  )
}

export default DevHero
