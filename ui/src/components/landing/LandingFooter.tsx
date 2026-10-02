import { Box, Container, Stack, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { isAppRoute } from '../../utils/links'
import { DISPLAY, fg, line, MONO, SANS } from './landingTokens'
import { LEGAL_NAV } from '../../content/legal'
import { RepoLink } from '../RepoLink'

const columns = [
  {
    heading: 'Product',
    links: [
      { label: 'Apps', href: '/#apps' },
      { label: 'Why Freepod', href: '/#why' },
      { label: 'Pricing', href: '/#pricing' },
      { label: 'Developers', href: '/dev' },
      { label: 'Docs', href: '/docs/' },
    ],
  },
  {
    heading: 'Company',
    links: [
      { label: 'About', href: '#' },
      { label: 'Mission', href: '/#why' },
      { label: 'Contact', href: '#' },
    ],
  },
  {
    heading: 'Legal',
    links: LEGAL_NAV.map((doc) => ({ label: doc.title, href: `/legal/${doc.slug}` })),
  },
]

const footerLinkSx = {
  fontFamily: SANS,
  fontSize: 14.5,
  color: fg.muted,
  transition: 'color 0.2s',
  '&:hover': { color: fg.primary },
}

/** Landing page footer with brand, nav columns and small print. */
export function LandingFooter() {
  return (
    <Box component="footer" sx={{ borderTop: `1px solid ${line.soft}`, py: { xs: 6, md: 8 } }}>
      <Container maxWidth="lg">
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          justifyContent="space-between"
          spacing={{ xs: 5, md: 4 }}
        >
          {/* Brand block */}
          <Box sx={{ maxWidth: 320 }}>
            <Stack direction="row" alignItems="center" spacing={1.25}>
              <Box component="img" src="/caelus.svg" alt="" sx={{ width: 28, height: 28 }} />
              <Typography
                sx={{
                  fontFamily: DISPLAY,
                  fontWeight: 600,
                  fontSize: 21,
                  color: fg.primary,
                  letterSpacing: '-0.02em',
                }}
              >
                Freepod
              </Typography>
            </Stack>
            <Typography
              sx={{ fontFamily: SANS, fontSize: 14.5, color: fg.muted, mt: 2, lineHeight: 1.6 }}
            >
              The European cloud that keeps your data yours. Private, open-source
              apps — free of ads, tracking and lock-in.
            </Typography>
            <RepoLink />
          </Box>

          {/* Link columns */}
          <Stack direction="row" spacing={{ xs: 5, sm: 8 }} flexWrap="wrap" useFlexGap>
            {columns.map((col) => (
              <Stack key={col.heading} spacing={1.5}>
                <Typography
                  sx={{
                    fontFamily: MONO,
                    fontSize: 11.5,
                    letterSpacing: '0.16em',
                    textTransform: 'uppercase',
                    color: fg.faint,
                  }}
                >
                  {col.heading}
                </Typography>
                {col.links.map((link) =>
                  isAppRoute(link.href) ? (
                    <Box key={link.label} component={RouterLink} to={link.href} sx={footerLinkSx}>
                      {link.label}
                    </Box>
                  ) : (
                    <Box key={link.label} component="a" href={link.href} sx={footerLinkSx}>
                      {link.label}
                    </Box>
                  ),
                )}
              </Stack>
            ))}
          </Stack>
        </Stack>

        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          justifyContent="space-between"
          alignItems={{ xs: 'flex-start', sm: 'center' }}
          spacing={1.5}
          sx={{ mt: { xs: 5, md: 7 }, pt: 3, borderTop: `1px solid ${line.softer}` }}
        >
          <Typography sx={{ fontFamily: SANS, fontSize: 13, color: fg.faint }}>
            © {new Date().getFullYear()} Freepod. All rights reserved.
          </Typography>
          <Typography sx={{ fontFamily: MONO, fontSize: 12, color: fg.faint, letterSpacing: '0.08em' }}>
            Hosted in the EU · Made for digital sovereignty
          </Typography>
        </Stack>
      </Container>
    </Box>
  )
}

export default LandingFooter
