import { Box, Container, Typography } from '@mui/material'
import { accent, DISPLAY, fg, line, MONO, SANS } from './landingTokens'
import SectionHeading from './SectionHeading'
import Reveal from './Reveal'

const steps = [
  {
    title: 'Claim your name',
    body: 'Pick a free domain name for your personal cloud, like alex.freepod.eu.',
  },
  {
    title: 'Install an app',
    body: 'Choose an app and a plan. Freepod spins it up in your personal cloud right away.',
  },
  {
    title: 'Use it from anywhere',
    body: 'From laptop, PC, or mobile. Using a browser, or install the native desktop or phone apps.',
  },
]

/** The three steps from sign-up to a running app. */
export function HowItWorks() {
  return (
    <Box component="section" id="how" sx={{ py: { xs: 9, md: 13 }, scrollMarginTop: 80 }}>
      <Container maxWidth="lg">
        <SectionHeading eyebrow="How it works" title="Up and running in three steps." />
        <Box
          component="ol"
          sx={{
            listStyle: 'none',
            p: 0,
            m: 0,
            mt: { xs: 6, md: 8 },
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: 'repeat(3, 1fr)' },
            gap: { xs: 4, md: 5 },
          }}
        >
          {steps.map((step, i) => (
            <Reveal key={step.title} delay={i * 100} component="li">
              <Box sx={{ borderTop: `2px solid ${line.soft}`, pt: 3, position: 'relative' }}>
                <Box
                  sx={{
                    position: 'absolute',
                    top: -2,
                    left: 0,
                    width: 48,
                    height: 2,
                    background: `linear-gradient(90deg, ${accent.blue}, ${accent.magenta})`,
                  }}
                />
                <Typography sx={{ fontFamily: MONO, fontSize: 13, color: fg.faint, letterSpacing: '0.1em' }}>
                  0{i + 1}
                </Typography>
                <Typography sx={{ fontFamily: DISPLAY, fontWeight: 500, fontSize: 26, mt: 1, color: fg.primary }}>
                  {step.title}
                </Typography>
                <Typography sx={{ fontFamily: SANS, fontSize: 16, lineHeight: 1.6, color: fg.muted, mt: 1.25 }}>
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
