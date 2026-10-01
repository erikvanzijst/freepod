import { useState } from 'react'
import { Box, Container, Stack, Typography } from '@mui/material'
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded'
import KeyboardRoundedIcon from '@mui/icons-material/KeyboardRounded'
import { accent, DISPLAY, fg, line, MONO, SANS } from '../landingTokens'
import DemoPlayer from './DemoPlayer'
import { demos, type DemoId } from './demos'

const copy: Record<DemoId, { title: string; body: string; steps: [string, string][] }> = {
  agent: {
    title: 'Deploy straight from your agent.',
    body: 'Your coding agent has already read the manual and understands everything there is to know about storage, builds, debugging, and more.',
    steps: [
      ['freepod skill install', 'I know kung fu'],
      ['"Create a link shortener…"', 'prompt your agent'],
      ['https://links.…', 'live immediately'],
    ],
  },
  manual: {
    title: 'Two commands to production.',
    body: 'No VPS, compose files, certificates, or reverse proxies to configure. Freepod detects your stack, builds it, and serves it on your domain.',
    steps: [
      ['freepod init', 'pick a Freepod hostname, or use a custom domain'],
      ['freepod deploy', 'build and release'],
      ['https://hello.…', 'live immediately'],
    ],
  },
}

const modes: { id: DemoId; label: string; icon: typeof AutoAwesomeRoundedIcon }[] = [
  { id: 'agent', label: 'With an agent', icon: AutoAwesomeRoundedIcon },
  { id: 'manual', label: 'Artisanal', icon: KeyboardRoundedIcon },
]

/** Section 1: the 0-to-live loop, played as a fake terminal + browser. */
export function DemoSection() {
  const [mode, setMode] = useState<DemoId>('agent')
  const text = copy[mode]

  return (
    <Box component="section" id="demo" sx={{ py: { xs: 8, md: 12 }, scrollMarginTop: 80 }}>
      <Container maxWidth="lg">
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: '4fr 8fr' },
            gap: { xs: 5, md: 7 },
            alignItems: 'start',
          }}
        >
          <Box>
            <Stack
              direction="row"
              role="tablist"
              sx={{
                display: 'inline-flex',
                p: 0.5,
                borderRadius: 999,
                border: `1px solid ${line.soft}`,
                background: 'rgba(255,255,255,0.03)',
              }}
            >
              {modes.map(({ id, label, icon: Icon }) => {
                const selected = id === mode
                return (
                  <Box
                    key={id}
                    component="button"
                    role="tab"
                    aria-selected={selected}
                    onClick={() => setMode(id)}
                    sx={{
                      all: 'unset',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 0.75,
                      px: 2,
                      py: 0.9,
                      borderRadius: 999,
                      fontFamily: SANS,
                      fontSize: 14.5,
                      fontWeight: 600,
                      color: selected ? '#fff' : fg.muted,
                      background: selected ? 'linear-gradient(120deg, #2563EB, #6D5BFF)' : 'transparent',
                      boxShadow: selected ? '0 8px 24px rgba(37,99,235,0.3)' : 'none',
                      transition: 'color 0.2s, background 0.2s',
                      '&:focus-visible': { outline: `2px solid ${accent.blue}`, outlineOffset: 2 },
                    }}
                  >
                    <Icon sx={{ fontSize: 17 }} />
                    {label}
                  </Box>
                )
              })}
            </Stack>

            <Typography
              component="h2"
              sx={{
                fontFamily: DISPLAY,
                fontWeight: 500,
                fontSize: { xs: 32, md: 40 },
                lineHeight: 1.1,
                letterSpacing: '-0.02em',
                color: fg.primary,
                mt: 4,
              }}
            >
              {text.title}
            </Typography>
            <Typography sx={{ fontFamily: SANS, fontSize: 17, lineHeight: 1.65, color: fg.muted, mt: 2 }}>
              {text.body}
            </Typography>

            <Stack component="ol" spacing={1.75} sx={{ listStyle: 'none', p: 0, m: 0, mt: 4 }}>
              {text.steps.map(([cmd, note], i) => (
                <Stack component="li" key={cmd} direction="row" spacing={1.75} alignItems="baseline">
                  <Typography sx={{ fontFamily: MONO, fontSize: 13, color: accent.cyan, minWidth: 22 }}>
                    {String(i + 1).padStart(2, '0')}
                  </Typography>
                  <Box>
                    <Typography sx={{ fontFamily: MONO, fontSize: 15, color: fg.primary }}>{cmd}</Typography>
                    <Typography sx={{ fontFamily: SANS, fontSize: 14.5, color: fg.faint }}>{note}</Typography>
                  </Box>
                </Stack>
              ))}
            </Stack>
          </Box>

          <DemoPlayer key={mode} demo={demos[mode]} />
        </Box>
      </Container>
    </Box>
  )
}

export default DemoSection
