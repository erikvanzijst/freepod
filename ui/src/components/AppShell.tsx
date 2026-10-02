import {
  AppBar,
  Avatar,
  Box,
  Button,
  Container,
  Divider,
  ListItemIcon,
  Menu,
  MenuItem,
  Stack,
  Toolbar,
  Typography,
} from '@mui/material'
import AdminPanelSettingsOutlinedIcon from '@mui/icons-material/AdminPanelSettingsOutlined'
import LogoutOutlinedIcon from '@mui/icons-material/LogoutOutlined'
import PersonOutlineOutlinedIcon from '@mui/icons-material/PersonOutlineOutlined'
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined'
import KeyboardArrowDownRoundedIcon from '@mui/icons-material/KeyboardArrowDownRounded'
import { useState, type PropsWithChildren } from 'react'
import { NavLink } from 'react-router-dom'
import EmailDialog from './EmailDialog'
import { useAuth } from '../state/AuthContext'
import AuroraBackground from './landing/AuroraBackground'
import AppFooter from './AppFooter'
import { accent, DISPLAY, fg, line } from './landing/landingTokens'

const keycloakAccountUrl = import.meta.env.VITE_KEYCLOAK_ACCOUNT_URL as
  | string
  | undefined

function AppShell({ children }: PropsWithChildren) {
  const { user, loading, email, setEmail } = useAuth()
  const showDialog = !loading && !user
  const [menuAnchor, setMenuAnchor] = useState<null | HTMLElement>(null)
  const menuOpen = Boolean(menuAnchor)
  const initial = user?.email?.[0]?.toUpperCase() ?? '?'

  function handleLogout() {
    if (keycloakAccountUrl) {
      // Production: sign out through oauth2-proxy → Keycloak
      window.location.href =
        '/oauth2/sign_out?rd=' + encodeURIComponent(window.location.origin + '/')
    } else {
      // No Keycloak configured: clear email via React state to show the
      // email dialog without a page reload.
      setEmail('')
    }
  }

  return (
    <Box
      sx={{
        minHeight: '100vh',
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Dimmed aurora, fixed to the viewport so it sits calmly behind scrolling
          content and ties the app to the landing page's atmosphere. */}
      <Box
        sx={{
          position: 'fixed',
          inset: 0,
          zIndex: 0,
          pointerEvents: 'none',
        }}
      >
        <AuroraBackground preset="whisper" subtle />
      </Box>
      <AppBar elevation={0} position="sticky">
        <Toolbar sx={{ gap: 2 }}>
          <Stack
            component={NavLink}
            to="/"
            direction="row"
            alignItems="center"
            spacing={1.25}
            sx={{ textDecoration: 'none' }}
          >
            <Box
              component="img"
              src="/caelus.svg"
              alt="Freepod"
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
          {/* The wordmark handles "home". Besides the developer page and docs, the bar
              carries no section nav; Admin and session actions live in the
              account menu. */}
          <Box
            component={NavLink}
            to="/dev"
            sx={{
              fontSize: 15,
              color: fg.muted,
              transition: 'color 0.2s',
              '&:hover': { color: fg.primary },
            }}
          >
            Developers
          </Box>
          <Box
            component="a"
            href="/docs/"
            sx={{
              fontSize: 15,
              color: fg.muted,
              transition: 'color 0.2s',
              '&:hover': { color: fg.primary },
            }}
          >
            Docs
          </Box>
          <Button
            onClick={(e) => setMenuAnchor(e.currentTarget)}
            aria-label="Account menu"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            endIcon={
              <KeyboardArrowDownRoundedIcon
                sx={{
                  transition: 'transform 0.2s',
                  transform: menuOpen ? 'rotate(180deg)' : 'none',
                }}
              />
            }
            sx={{
              color: fg.muted,
              textTransform: 'none',
              fontWeight: 500,
              borderRadius: 999,
              pl: 0.75,
              pr: 1.25,
              py: 0.5,
              border: `1px solid ${line.soft}`,
              background: 'rgba(255,255,255,0.03)',
              '&:hover': {
                background: 'rgba(255,255,255,0.06)',
                color: fg.primary,
                borderColor: 'rgba(148,163,184,0.35)',
              },
              '& .MuiButton-endIcon': { ml: 0.5 },
            }}
          >
            <Avatar
              sx={{
                width: 26,
                height: 26,
                fontSize: 13,
                fontWeight: 600,
                mr: 1,
                color: '#fff',
                background: `linear-gradient(135deg, ${accent.blue}, ${accent.magenta})`,
              }}
            >
              {initial}
            </Avatar>
            <Box
              component="span"
              sx={{ display: { xs: 'none', sm: 'inline' }, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis' }}
            >
              {user ? user.email : 'No email set'}
            </Box>
          </Button>
          <Menu
            anchorEl={menuAnchor}
            open={menuOpen}
            onClose={() => setMenuAnchor(null)}
            transformOrigin={{ horizontal: 'right', vertical: 'top' }}
            anchorOrigin={{ horizontal: 'right', vertical: 'bottom' }}
            slotProps={{ paper: { sx: { mt: 1, minWidth: 200 } } }}
          >
            {user?.is_admin && (
              <MenuItem
                component={NavLink}
                to="/admin"
                onClick={() => setMenuAnchor(null)}
              >
                <ListItemIcon>
                  <AdminPanelSettingsOutlinedIcon fontSize="small" />
                </ListItemIcon>
                Admin
              </MenuItem>
            )}
            {user?.is_admin && <Divider />}
            {/* The user's own account, not a privileged feature: shown to
                everyone, and above Profile because it is in-app rather than a
                hop out to the identity provider. */}
            <MenuItem
              component={NavLink}
              to="/settings"
              onClick={() => setMenuAnchor(null)}
            >
              <ListItemIcon>
                <SettingsOutlinedIcon fontSize="small" />
              </ListItemIcon>
              Settings
            </MenuItem>
            {/* Always shown so the menu is identical across environments. In
                local dev VITE_KEYCLOAK_ACCOUNT_URL is unset, so the href is
                empty; in production it points at the Keycloak account portal
                and opens in a new tab. */}
            <MenuItem
              component="a"
              href={keycloakAccountUrl ?? ''}
              target={keycloakAccountUrl ? '_blank' : undefined}
              rel={keycloakAccountUrl ? 'noopener noreferrer' : undefined}
              onClick={() => setMenuAnchor(null)}
            >
              <ListItemIcon>
                <PersonOutlineOutlinedIcon fontSize="small" />
              </ListItemIcon>
              Profile
            </MenuItem>
            <MenuItem onClick={handleLogout}>
              <ListItemIcon>
                <LogoutOutlinedIcon fontSize="small" />
              </ListItemIcon>
              Logout
            </MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <Container
        maxWidth="xl"
        sx={{ py: 6, position: 'relative', zIndex: 1, flex: 1 }}
      >
        {children}
      </Container>
      <AppFooter />
      <EmailDialog
        open={showDialog}
        current={email}
        onSave={(value) => {
          setEmail(value)
        }}
      />
    </Box>
  )
}

export default AppShell
