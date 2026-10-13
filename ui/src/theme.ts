import { createTheme } from '@mui/material/styles'
import { accent, cardSurface, fg, ink, line, MONO, SANS } from './components/landing/landingTokens'

declare module '@mui/material/styles' {
  interface Palette {
    surface: Palette['primary']
  }
  interface PaletteOptions {
    surface?: PaletteOptions['primary']
  }
}

/**
 * In-app theme (Dashboard + Admin). Shares its palette and type stack with the
 * anonymous landing page via `landingTokens`, so the authenticated surfaces read
 * as the same product: dark "digital sovereignty" ink, glassy cards, Schibsted
 * Grotesk body/UI type and a blue→violet accent. The landing page paints its own
 * background on top of this theme, so flipping the app dark leaves it untouched.
 */

/** Primary CTA fill, matching the landing nav's "Create account" button. */
const PRIMARY_GRADIENT = 'linear-gradient(120deg, #2563EB, #6D5BFF)'
const PRIMARY_GRADIENT_HOVER = 'linear-gradient(120deg, #1d4fd0, #5d4bf0)'

export const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: accent.blue,
      light: '#89A9FF',
      dark: accent.blueDeep,
      contrastText: '#0B1020',
    },
    secondary: {
      main: accent.magenta,
      light: accent.pink,
      dark: '#b4236c',
    },
    success: { main: '#34D399' },
    warning: { main: '#FBBF24' },
    error: { main: '#F87171' },
    info: { main: accent.cyan },
    background: {
      default: ink.base,
      paper: ink.raised,
    },
    surface: {
      main: '#F4F6FB',
      contrastText: ink.base,
    },
    text: {
      primary: fg.primary,
      secondary: fg.muted,
      disabled: fg.faint,
    },
    divider: line.soft,
  },
  typography: {
    fontFamily: SANS,
    h1: { fontWeight: 600, letterSpacing: '-0.02em' },
    h2: { fontWeight: 600, letterSpacing: '-0.02em' },
    h3: { fontWeight: 600, letterSpacing: '-0.02em' },
    h4: { fontWeight: 600, letterSpacing: '-0.015em' },
    h5: { fontWeight: 600, letterSpacing: '-0.01em' },
    h6: { fontWeight: 600, letterSpacing: '-0.01em' },
    button: { textTransform: 'none', fontWeight: 600 },
    overline: {
      fontFamily: MONO,
      fontSize: 12,
      letterSpacing: '0.22em',
      fontWeight: 400,
    },
  },
  shape: {
    borderRadius: 10,
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: ink.base,
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: ink.raised,
        },
        // Cards, dialogs and menus render as glassy raised surfaces.
        outlined: {
          border: cardSurface.border,
          background: cardSurface.background,
          backdropFilter: cardSurface.backdropFilter,
        },
      },
    },
    MuiCard: {
      defaultProps: { variant: 'outlined' },
      styleOverrides: {
        root: {
          background: cardSurface.background,
          border: cardSurface.border,
          backdropFilter: cardSurface.backdropFilter,
          borderRadius: 12,
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: {
          borderRadius: 999,
          paddingInline: 18,
        },
        containedPrimary: {
          color: '#fff',
          background: PRIMARY_GRADIENT,
          boxShadow: '0 8px 24px rgba(37,99,235,0.35)',
          '&:hover': { background: PRIMARY_GRADIENT_HOVER },
          '&.Mui-disabled': {
            background: 'rgba(148,163,184,0.16)',
            color: fg.faint,
            boxShadow: 'none',
          },
        },
        outlined: {
          borderColor: line.soft,
          '&:hover': {
            borderColor: 'rgba(148,163,184,0.35)',
            background: 'rgba(255,255,255,0.04)',
          },
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          background: 'rgba(7, 10, 20, 0.62)',
          color: fg.primary,
          borderBottom: `1px solid ${line.softer}`,
          backdropFilter: 'blur(14px)',
          backgroundImage: 'none',
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          background: 'rgba(255,255,255,0.03)',
          '& .MuiOutlinedInput-notchedOutline': {
            borderColor: line.soft,
          },
          '&:hover .MuiOutlinedInput-notchedOutline': {
            borderColor: 'rgba(148,163,184,0.35)',
          },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        outlined: {
          borderColor: line.soft,
        },
      },
    },
    MuiDivider: {
      styleOverrides: {
        root: { borderColor: line.soft },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          background: ink.abyss,
          border: `1px solid ${line.soft}`,
          fontSize: 12,
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          '&.Mui-selected': {
            background: `${accent.blue}1f`,
            '&:hover': { background: `${accent.blue}2a` },
          },
        },
      },
    },
  },
})
