import { Box, Button, Container, Stack, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { DISPLAY, fg, line } from './landingTokens'
import { useAuth } from '../../state/AuthContext'

export interface NavLink {
  label: string
  /** An in-page `#anchor`, or an app path routed client-side. */
  href: string
}

interface LandingNavProps {
  onSignup: () => void
  links?: NavLink[]
}

const defaultLinks: NavLink[] = [
  { label: 'Apps', href: '#apps' },
  { label: 'Why Freepod', href: '#why' },
  { label: 'Pricing', href: '#pricing' },
  { label: 'Developers', href: '/dev' },
]

const navLinkSx = {
  fontSize: 15,
  color: fg.muted,
  transition: 'color 0.2s',
  '&:hover': { color: fg.primary },
}

/** Sticky, translucent top navigation for the landing pages. */
export function LandingNav({ onSignup, links = defaultLinks }: LandingNavProps) {
  const { user } = useAuth()

  return (
    <Box
      component="header"
      sx={{
        position: 'sticky',
        top: 0,
        zIndex: 20,
        borderBottom: `1px solid ${line.softer}`,
        background: 'rgba(7, 10, 20, 0.62)',
        backdropFilter: 'blur(14px)',
      }}
    >
      <Container maxWidth="lg">
        <Stack
          direction="row"
          alignItems="center"
          sx={{ height: 72, gap: 2 }}
        >
          {/* Brand */}
          <Stack component={RouterLink} to="/" direction="row" alignItems="center" spacing={1.25}>
            <Box
              component="img"
              src="/caelus.svg"
              alt=""
              sx={{ width: 30, height: 30 }}
            />
            <Typography
              sx={{
                fontFamily: DISPLAY,
                fontWeight: 600,
                fontSize: 22,
                letterSpacing: '-0.02em',
                color: fg.primary,
              }}
            >
              Freepod
            </Typography>
          </Stack>

          <Box sx={{ flex: 1 }} />

          {/* Section links — hidden on small screens */}
          <Stack
            direction="row"
            spacing={3.5}
            sx={{ display: { xs: 'none', md: 'flex' }, mr: 1 }}
          >
            {links.map((link) =>
              link.href.startsWith('/') ? (
                <Box key={link.href} component={RouterLink} to={link.href} sx={navLinkSx}>
                  {link.label}
                </Box>
              ) : (
                <Box key={link.href} component="a" href={link.href} sx={navLinkSx}>
                  {link.label}
                </Box>
              ),
            )}
          </Stack>

          {!user && (
            <Button
              onClick={onSignup}
              sx={{
                display: { xs: 'none', sm: 'inline-flex' },
                color: fg.muted,
                fontSize: 15,
                px: 1.5,
                '&:hover': { color: fg.primary, background: 'transparent' },
              }}
            >
              Log in
            </Button>
          )}
          <Button
            variant="contained"
            {...(user ? { component: RouterLink, to: '/' } : { onClick: onSignup })}
            sx={{
              borderRadius: 999,
              px: 2.5,
              fontWeight: 600,
              whiteSpace: 'nowrap',
              color: '#fff',
              background: 'linear-gradient(120deg, #2563EB, #6D5BFF)',
              boxShadow: '0 8px 24px rgba(37,99,235,0.35)',
              '&:hover': {
                background: 'linear-gradient(120deg, #1d4fd0, #5d4bf0)',
              },
            }}
          >
            {user ? 'Dashboard' : 'Create account'}
          </Button>
        </Stack>
      </Container>
    </Box>
  )
}

export default LandingNav
