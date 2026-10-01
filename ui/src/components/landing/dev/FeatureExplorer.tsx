import { useState } from 'react'
import { Box, Container, Stack, Typography } from '@mui/material'
import { accent, cardSurface, DISPLAY, fg, line, MONO, SANS } from '../landingTokens'
import SectionHeading from '../SectionHeading'
import Reveal from '../Reveal'
import CodeBlock from './CodeBlock'
import { features, type Feature } from './features'

const skillSnippet = [
  {
    label: 'Terminal',
    lang: 'shell' as const,
    code: `$ freepod skill install
  Claude Code  ~/.claude/skills/deploy-to-freepod
  Codex        ~/.codex/skills/deploy-to-freepod
  OpenCode     ~/.config/opencode/skills/deploy-to-freepod
Installed 'deploy-to-freepod' for Claude Code, Codex and OpenCode.`,
  },
]

const supportedAgents = ['Claude Code', 'Codex', 'OpenCode', 'Amp', 'Gemini CLI', 'Qwen Code', 'Mistral Vibe']

function FeatureCode({ feature, lang, onLang }: { feature: Feature; lang: string; onLang: (l: string) => void }) {
  return <CodeBlock snippets={feature.snippets} active={lang} onSelect={onLang} />
}

/**
 * Section 2: the platform's building blocks as a selectable list beside a
 * code panel. The language tab is shared across features, so a Go developer
 * picks Go once.
 */
export function FeatureExplorer() {
  const [activeId, setActiveId] = useState(features[0].id)
  const [lang, setLang] = useState('Python')
  const active = features.find((f) => f.id === activeId) ?? features[0]

  return (
    <Box component="section" id="features" sx={{ py: { xs: 9, md: 14 }, scrollMarginTop: 80 }}>
      <Container maxWidth="lg">
        <SectionHeading
          eyebrow="Batteries included"
          title="All the basics covered."
          subtitle="Each deployment comes with its own database, bucket, config and authentication."
        />

        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: '5fr 7fr' },
            gap: { xs: 3, md: 5 },
            mt: { xs: 6, md: 8 },
            alignItems: 'start',
          }}
        >
          <Stack role="tablist" aria-orientation="vertical" sx={{ border: `1px solid ${line.soft}`, borderRadius: '16px', overflow: 'hidden' }}>
            {features.map((feature, i) => {
              const Icon = feature.icon
              const selected = feature.id === active.id
              return (
                <Box key={feature.id} sx={{ borderTop: i ? `1px solid ${line.soft}` : 'none' }}>
                  <Box
                    component="button"
                    role="tab"
                    aria-selected={selected}
                    onClick={() => setActiveId(feature.id)}
                    sx={{
                      all: 'unset',
                      boxSizing: 'border-box',
                      cursor: 'pointer',
                      display: 'flex',
                      gap: 2,
                      width: '100%',
                      p: { xs: 2.5, md: 3 },
                      background: selected ? 'rgba(255,255,255,0.045)' : 'transparent',
                      boxShadow: selected ? `inset 3px 0 0 ${feature.color}` : 'none',
                      transition: 'background 0.25s',
                      '&:hover': { background: 'rgba(255,255,255,0.03)' },
                      '&:focus-visible': { outline: `2px solid ${accent.blue}`, outlineOffset: -2 },
                    }}
                  >
                    <Stack
                      sx={{
                        flexShrink: 0,
                        width: 40,
                        height: 40,
                        borderRadius: 2,
                        alignItems: 'center',
                        justifyContent: 'center',
                        background: `${feature.color}1f`,
                        border: `1px solid ${feature.color}3a`,
                      }}
                    >
                      <Icon sx={{ fontSize: 21, color: feature.color }} />
                    </Stack>
                    <Box>
                      <Typography sx={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 19, color: fg.primary }}>
                        {feature.title}
                      </Typography>
                      <Box
                        sx={{
                          display: 'grid',
                          gridTemplateRows: selected ? '1fr' : '0fr',
                          transition: 'grid-template-rows 0.35s cubic-bezier(0.22,1,0.36,1)',
                        }}
                      >
                        <Typography
                          sx={{
                            overflow: 'hidden',
                            fontFamily: SANS,
                            fontSize: 15,
                            lineHeight: 1.6,
                            color: fg.muted,
                            pt: selected ? 0.75 : 0,
                          }}
                        >
                          {feature.blurb}
                        </Typography>
                      </Box>
                    </Box>
                  </Box>
                  {selected && (
                    <Box sx={{ display: { xs: 'block', md: 'none' }, px: 1.5, pb: 1.5 }}>
                      <FeatureCode feature={feature} lang={lang} onLang={setLang} />
                    </Box>
                  )}
                </Box>
              )
            })}
          </Stack>

          <Box sx={{ display: { xs: 'none', md: 'block' }, position: 'sticky', top: 104 }}>
            <FeatureCode feature={active} lang={lang} onLang={setLang} />
          </Box>
        </Box>

        <Reveal>
          <Box
            sx={{
              mt: { xs: 6, md: 10 },
              p: { xs: 3, md: 5 },
              borderRadius: 5,
              ...cardSurface,
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', md: '5fr 7fr' },
              gap: { xs: 3, md: 5 },
              alignItems: 'center',
            }}
          >
            <Box>
              <Typography
                sx={{ fontFamily: MONO, fontSize: 12.5, letterSpacing: '0.22em', textTransform: 'uppercase', color: accent.pink, mb: 1.5 }}
              >
                Agent-ready
              </Typography>
              <Typography
                component="h3"
                sx={{ fontFamily: DISPLAY, fontWeight: 500, fontSize: { xs: 26, md: 32 }, lineHeight: 1.15, color: fg.primary }}
              >
                Your agent already knows all of this.
              </Typography>
              <Typography sx={{ fontFamily: SANS, fontSize: 16, lineHeight: 1.65, color: fg.muted, mt: 2 }}>
                Install the Freepod skill and your agent effortlessly navigates the Freepod platform.
                Add persistent storage or authentication, understand constraints, or debug a failed deploy.
              </Typography>
              <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1} sx={{ mt: 2.5 }}>
                {supportedAgents.map((agent) => (
                  <Box
                    key={agent}
                    sx={{
                      px: 1.25,
                      py: 0.4,
                      borderRadius: 999,
                      fontFamily: SANS,
                      fontSize: 13,
                      color: fg.muted,
                      background: 'rgba(255,255,255,0.04)',
                      border: '1px solid rgba(255,255,255,0.08)',
                    }}
                  >
                    {agent}
                  </Box>
                ))}
              </Stack>
            </Box>
            <CodeBlock snippets={skillSnippet} />
          </Box>
        </Reveal>
      </Container>
    </Box>
  )
}

export default FeatureExplorer
