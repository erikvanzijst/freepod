import { Box, Container, Typography } from '@mui/material'
import { accent, DISPLAY, fg, line, MONO, SANS } from './landingTokens'
import Reveal from './Reveal'

/** What Freepod does, why it exists and who it is for, in one paragraph. */
export function AboutFreepod() {
  return (
    <Box component="section" id="about" sx={{ py: { xs: 3, md: 4 }, scrollMarginTop: 80 }}>
      <Container maxWidth="md">
        <Reveal sx={{ borderTop: `1px solid ${line.soft}`, borderBottom: `1px solid ${line.soft}`, py: { xs: 5, md: 7 } }}>
          <Typography
            sx={{ fontFamily: MONO, fontSize: 12.5, letterSpacing: '0.22em', textTransform: 'uppercase', color: accent.cyan, mb: 3 }}
          >
            Why we built Freepod
          </Typography>
          <Typography sx={{ fontFamily: DISPLAY, fontWeight: 400, fontSize: { xs: 22, md: 27 }, lineHeight: 1.5, color: fg.primary }}>
            Most of us just want our technology to work and stay out of sight. But where our photos,
            documents and messages end up, and what they're used for, still matters. We built Freepod to
            offer the technology you depend on every day, while respecting your control and privacy, using
            apps and services designed around these principles.{' '}
            <Box component="span" sx={{ color: accent.blue }}>
              And with all our code open source, we have the receipts to prove it.
            </Box>
          </Typography>
          <Typography sx={{ fontFamily: SANS, fontSize: { xs: 16.5, md: 18 }, lineHeight: 1.65, color: fg.muted, mt: 3 }}>
            For households, independent shops and growing businesses alike: all the control of having your own
            cloud, with none of the work of running one.
          </Typography>
        </Reveal>
      </Container>
    </Box>
  )
}

export default AboutFreepod
