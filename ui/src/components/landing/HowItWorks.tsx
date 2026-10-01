import { Box, Container, Typography } from '@mui/material'
import { accent, cardSurface, DISPLAY, fg, MONO, SANS } from './landingTokens'
import SectionHeading from './SectionHeading'
import Reveal from './Reveal'

const steps = [
  {
    n: '01',
    title: 'Choose an app',
    body: 'Pick from our catalogue of vetted open-source apps and the plan that fits — from a tiny password vault to terabytes of photos.',
    color: accent.blue,
  },
  {
    n: '02',
    title: 'We spin up your pod',
    body: 'Your own dedicated instance is provisioned on European infrastructure, with isolated storage and automatic encrypted HTTPS.',
    color: accent.magenta,
  },
  {
    n: '03',
    title: 'Make it yours',
    body: 'Bring your own domain, invite family or teammates, and use it from any device. Export your data — or leave — whenever you like.',
    color: accent.cyan,
  },
]

/** Three-step "how it works" explainer. */
export function HowItWorks() {
  return (
    <Box component="section" sx={{ py: { xs: 9, md: 14 } }}>
      <Container maxWidth="lg">
        <SectionHeading
          eyebrow="How it works"
          title="From sign-up to sovereign in minutes."
        />

        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: '1fr 1fr 1fr' },
            gap: 2.5,
            mt: { xs: 6, md: 8 },
          }}
        >
          {steps.map((step, i) => (
            <Reveal key={step.n} delay={i * 110}>
              <Box
                sx={{
                  height: '100%',
                  p: 4,
                  borderRadius: 4,
                  ...cardSurface,
                }}
              >
                <Typography
                  sx={{
                    fontFamily: MONO,
                    fontSize: 40,
                    fontWeight: 700,
                    lineHeight: 1,
                    color: 'transparent',
                    WebkitTextStroke: `1px ${step.color}99`,
                  }}
                >
                  {step.n}
                </Typography>
                <Typography
                  sx={{
                    fontFamily: DISPLAY,
                    fontWeight: 600,
                    fontSize: 23,
                    color: fg.primary,
                    mt: 2.5,
                  }}
                >
                  {step.title}
                </Typography>
                <Typography
                  sx={{
                    fontFamily: SANS,
                    fontSize: 15.5,
                    lineHeight: 1.6,
                    color: fg.muted,
                    mt: 1.5,
                  }}
                >
                  {step.body}
                </Typography>
              </Box>
            </Reveal>
          ))}
        </Box>
      </Container>
    </Box>
  )
}

export default HowItWorks
