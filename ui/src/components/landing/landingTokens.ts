/**
 * Design tokens and content data for the anonymous Freepod landing page.
 *
 * The landing page intentionally diverges from the utilitarian in-app theme:
 * a darker, editorial "digital sovereignty" aesthetic. Keeping the palette,
 * type stack and (provisional) content/pricing data in one module makes design
 * iteration fast and keeps the section components focused on layout.
 */
import type { SvgIconComponent } from '@mui/icons-material'
import PhotoLibraryRoundedIcon from '@mui/icons-material/PhotoLibraryRounded'
import FolderRoundedIcon from '@mui/icons-material/FolderRounded'
import ForumRoundedIcon from '@mui/icons-material/ForumRounded'
import GroupsRoundedIcon from '@mui/icons-material/GroupsRounded'
import LockRoundedIcon from '@mui/icons-material/LockRounded'
import MenuBookRoundedIcon from '@mui/icons-material/MenuBookRounded'
import PeopleRoundedIcon from '@mui/icons-material/PeopleRounded'
import AppsRoundedIcon from '@mui/icons-material/AppsRounded'

/* ── Type stack ──────────────────────────────────────────────────────────── */
/** Editorial serif for display headlines — gravitas, trust, character. */
export const DISPLAY = "'Fraunces Variable', 'Fraunces', Georgia, 'Times New Roman', serif"
/** European-feeling grotesque for body and UI. */
export const SANS = "'Schibsted Grotesk Variable', 'Schibsted Grotesk', system-ui, sans-serif"
/** Mono for eyebrow labels and small technical accents. */
export const MONO = "'Space Mono', ui-monospace, 'SFMono-Regular', monospace"

/* ── Palette ─────────────────────────────────────────────────────────────── */
export const ink = {
  /** Deepest background. */
  abyss: '#070A14',
  /** Primary background. */
  base: '#0B1020',
  /** Slightly raised panel base. */
  raised: '#10162B',
}

export const accent = {
  blue: '#5B8CFF',
  blueDeep: '#2563EB',
  cyan: '#38BDF8',
  magenta: '#EC4899',
  pink: '#F472B6',
}

export const fg = {
  primary: '#F4F6FB',
  muted: '#A6B0CC',
  faint: '#6F7C9B',
}

export const line = {
  soft: 'rgba(148, 163, 184, 0.14)',
  softer: 'rgba(148, 163, 184, 0.08)',
}

/** Glassy card surface used across sections. */
export const cardSurface = {
  background:
    'linear-gradient(160deg, rgba(255,255,255,0.055), rgba(255,255,255,0.018))',
  border: '1px solid rgba(255,255,255,0.08)',
  backdropFilter: 'blur(10px)',
}

/* ── Per-product accent colors ─────────────────────────────────────────────
 * Purely presentational. Each product gets a stable accent derived from a hash
 * of its name, so the color is deterministic (same product, same color across
 * sections) and reasonably spread across the palette — without hardcoding any
 * product identity here. Product marketing copy (category, replaces, blurb) is
 * product data and comes from the API, not from here.
 */
const accentPalette = [accent.blue, accent.cyan, accent.magenta, accent.pink]

/** Deterministic djb2 string hash, returned as an unsigned 32-bit integer. */
function hashName(name: string): number {
  let hash = 5381
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 33) ^ name.charCodeAt(i)
  }
  return hash >>> 0
}

/**
 * Resolve a product's accent color: a stable, deterministic pick from the
 * palette based on a hash of the (normalized) product name.
 */
export function accentForProduct(name: string): string {
  return accentPalette[hashName(name.trim().toLowerCase()) % accentPalette.length]
}

/* ── Category icons ─────────────────────────────────────────────────────────
 * Categories are far more static than the product catalog, so a small icon map
 * keyed by category label is an acceptable bit of hardcoding here. Unknown or
 * edited categories fall back to a generic icon, so this never breaks.
 */
const categoryIcons: Record<string, SvgIconComponent> = {
  photos: PhotoLibraryRoundedIcon,
  'files & documents': FolderRoundedIcon,
  'chat & messaging': ForumRoundedIcon,
  'team collaboration': GroupsRoundedIcon,
  'passwords & passkeys': LockRoundedIcon,
  'knowledge & wikis': MenuBookRoundedIcon,
  'forums & communities': PeopleRoundedIcon,
}

/** Categories most people already keep in the cloud come first; unknown ones follow. */
const categoryOrder = [
  'photos',
  'files & documents',
  'passwords & passkeys',
  'chat & messaging',
  'team collaboration',
  'knowledge & wikis',
  'forums & communities',
]

/** Sort comparator for category labels, by `categoryOrder`. */
export function compareCategories(a: string, b: string): number {
  const rank = (c: string) => {
    const i = categoryOrder.indexOf(c.trim().toLowerCase())
    return i === -1 ? categoryOrder.length : i
  }
  return rank(a) - rank(b)
}

/** The generic icon for a category label, with a sensible fallback. */
export function categoryIcon(category: string): SvgIconComponent {
  return categoryIcons[category.trim().toLowerCase()] ?? AppsRoundedIcon
}

/* ── Buttons ─────────────────────────────────────────────────────────────── */
export const primaryButtonSx = {
  borderRadius: 999,
  px: 3.5,
  py: 1.4,
  fontSize: 16.5,
  fontWeight: 600,
  color: '#fff',
  background: 'linear-gradient(120deg, #2563EB, #7C5BFF 55%, #EC4899)',
  boxShadow: '0 14px 40px rgba(124,91,255,0.35)',
  transition: 'transform 0.2s, box-shadow 0.2s',
  '&:hover': {
    transform: 'translateY(-2px)',
    boxShadow: '0 18px 48px rgba(124,91,255,0.45)',
    background: 'linear-gradient(120deg, #1d4fd0, #6d4bf0 55%, #db3b89)',
  },
} as const

export const secondaryButtonSx = {
  borderRadius: 999,
  px: 3.25,
  py: 1.4,
  fontSize: 16.5,
  fontWeight: 600,
  color: fg.primary,
  border: '1px solid rgba(255,255,255,0.18)',
  background: 'rgba(255,255,255,0.03)',
  '&:hover': { background: 'rgba(255,255,255,0.08)', borderColor: 'rgba(255,255,255,0.3)' },
} as const
