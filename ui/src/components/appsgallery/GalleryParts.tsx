import { createElement, useRef, useState } from 'react'
import { Box, Button, IconButton, InputAdornment, Stack, TextField, Typography } from '@mui/material'
import SearchRounded from '@mui/icons-material/SearchRounded'
import CloseRounded from '@mui/icons-material/CloseRounded'
import ArrowForwardRounded from '@mui/icons-material/ArrowForwardRounded'
import { Link as RouterLink } from 'react-router-dom'
import { accent, categoryIcon, DISPLAY, fg, line, MONO, SANS } from '../landing/landingTokens'
import { formatEuro } from '../landing/usePricing'
import { FeatureIcon } from '../apppage/FeatureList'
import InstallButton from '../apppage/InstallButton'
import ScreenshotStrip from '../apppage/ScreenshotStrip'
import ScreenshotLightbox from '../apppage/ScreenshotLightbox'
import { useSlashToFocus } from '../../utils/useSlashToFocus'
import type { GalleryApp } from './useGallery'
import { usePreview } from './useGallery'

const eyebrowSx = {
  fontFamily: MONO,
  fontSize: 12,
  letterSpacing: '0.18em',
  textTransform: 'uppercase',
  color: fg.faint,
} as const

export function GalleryIntro() {
  return (
    <Box>
      <Typography sx={eyebrowSx}>App catalog</Typography>
      <Typography
        component="h1"
        sx={{
          mt: 1.5,
          fontFamily: DISPLAY,
          fontWeight: 500,
          fontSize: { xs: 34, md: 52 },
          lineHeight: 1.05,
          letterSpacing: '-0.02em',
          textWrap: 'balance',
        }}
      >
        Open-source apps, ready to run.
      </Typography>
      <Typography sx={{ mt: 2, maxWidth: 680, fontSize: { xs: 16, md: 18 }, color: fg.muted, lineHeight: 1.6 }}>
        Every app runs in its own private pod, hosted in the EU. Install in a minute, take your data with you
        whenever you like.
      </Typography>
    </Box>
  )
}

interface SearchFieldProps {
  value: string
  onChange: (v: string) => void
  fullWidth?: boolean
  placeholder?: string
  /** Focus this field when "/" is pressed; only one field on screen should claim it. */
  slashShortcut?: boolean
}

const kbdSx = {
  display: { xs: 'none', sm: 'inline-grid' },
  placeItems: 'center',
  minWidth: 22,
  height: 22,
  px: 0.5,
  borderRadius: '6px',
  border: `1px solid ${line.soft}`,
  fontFamily: MONO,
  fontSize: 12,
  color: fg.faint,
  mr: 0.5,
} as const

export function SearchField({
  value,
  onChange,
  fullWidth = false,
  placeholder = 'Search apps, or what you need them for…',
  slashShortcut = false,
}: SearchFieldProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  useSlashToFocus(inputRef, slashShortcut)

  // Callers keep the query in the URL, which React Router updates a render or
  // more behind the keystroke. The field shows its own text and ignores the URL
  // echoing values it sent, adopting only values it never sent (a reset elsewhere,
  // back/forward).
  const [draft, setDraft] = useState(value)
  const [sent, setSent] = useState<string[]>([])
  const [seen, setSeen] = useState(value)
  if (value !== seen) {
    setSeen(value)
    const echoed = sent.indexOf(value)
    if (echoed === -1) {
      setDraft(value)
      setSent([])
    } else {
      setSent(sent.slice(echoed + 1))
    }
  }
  const change = (next: string) => {
    setDraft(next)
    setSent((previous) => [...previous, next])
    onChange(next)
  }

  return (
    <TextField
      inputRef={inputRef}
      value={draft}
      onKeyDown={(e) => {
        if (e.key === 'Escape') inputRef.current?.blur()
      }}
      onChange={(e) => change(e.target.value)}
      placeholder={placeholder}
      fullWidth={fullWidth}
      size="small"
      slotProps={{
        input: {
          startAdornment: (
            <InputAdornment position="start">
              <SearchRounded sx={{ fontSize: 20, color: fg.faint }} />
            </InputAdornment>
          ),
          endAdornment: draft ? (
            <InputAdornment position="end">
              <IconButton aria-label="Clear search" edge="end" size="small" onClick={() => change('')} sx={{ color: fg.muted }}>
                <CloseRounded sx={{ fontSize: 18 }} />
              </IconButton>
            </InputAdornment>
          ) : (
            slashShortcut && (
              <InputAdornment position="end">
                <Box component="kbd" title="Press / to search" sx={kbdSx}>
                  /
                </Box>
              </InputAdornment>
            )
          ),
          sx: { borderRadius: 999, fontFamily: SANS, fontSize: 15, height: 44, background: 'rgba(255,255,255,0.03)' },
        },
      }}
      sx={fullWidth ? undefined : { minWidth: { md: 360 } }}
    />
  )
}

interface CategoryFilterProps {
  categories: { name: string; count: number }[]
  total: number
  active: string
  onSelect: (c: string) => void
}

const chipSx = (active: boolean) => ({
  flex: '0 0 auto',
  display: 'inline-flex',
  alignItems: 'center',
  gap: 0.75,
  px: 1.5,
  py: 0.6,
  borderRadius: 999,
  fontSize: 13.5,
  cursor: 'pointer',
  fontFamily: SANS,
  color: active ? fg.primary : fg.muted,
  border: `1px solid ${active ? 'rgba(91,140,255,0.5)' : line.soft}`,
  background: active ? 'rgba(91,140,255,0.12)' : 'transparent',
  '&:hover': { color: fg.primary, borderColor: 'rgba(148,163,184,0.4)' },
})

/** Horizontal category chips, "All" first. */
export function CategoryChips({ categories, total, active, onSelect }: CategoryFilterProps) {
  return (
    <Stack
      direction="row"
      sx={{
        gap: 1,
        flexWrap: { xs: 'nowrap', md: 'wrap' },
        overflowX: 'auto',
        scrollbarWidth: 'none',
        '&::-webkit-scrollbar': { display: 'none' },
        mx: { xs: -2, sm: 0 },
        px: { xs: 2, sm: 0 },
        maskImage: { xs: 'linear-gradient(90deg, transparent 0, #000 16px, #000 calc(100% - 32px), transparent)', md: 'none' },
      }}
    >
      <Box component="button" onClick={() => onSelect('')} sx={chipSx(!active)}>
        All <Count n={total} />
      </Box>
      {categories.map((c) => (
        <Box component="button" key={c.name} onClick={() => onSelect(c.name)} sx={chipSx(c.name === active)}>
          {createElement(categoryIcon(c.name), { sx: { fontSize: 16 } })}
          {c.name} <Count n={c.count} />
        </Box>
      ))}
    </Stack>
  )
}

function Count({ n }: { n: number }) {
  return <Box component="span" sx={{ fontSize: 12, color: fg.faint, fontFamily: MONO }}>{n}</Box>
}

export function PriceTag({ app }: { app: GalleryApp }) {
  if (app.fromCents === undefined) return null
  return (
    <Typography sx={{ fontSize: 13.5, color: fg.muted, whiteSpace: 'nowrap' }}>
      {app.fromCents === null ? 'Free' : <>from <b style={{ color: fg.primary }}>{formatEuro(app.fromCents)}</b>/mo</>}
    </Typography>
  )
}

export function RunningBadge({ count }: { count: number }) {
  if (!count) return null
  return (
    <Box
      component="span"
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 0.75,
        px: 1,
        py: 0.25,
        borderRadius: 999,
        fontSize: 12,
        color: '#86EFAC',
        background: 'rgba(34,197,94,0.1)',
        border: '1px solid rgba(34,197,94,0.25)',
        whiteSpace: 'nowrap',
      }}
    >
      <Box component="span" sx={{ width: 6, height: 6, borderRadius: '50%', background: '#22C55E' }} />
      {count > 1 ? `${count} running` : 'Running'}
    </Box>
  )
}

/** Marks a product only administrators see in the catalog. */
export function VisibilityBadge({ app }: { app: GalleryApp }) {
  if (app.visibility === 'public') return null
  return (
    <Box
      component="span"
      title={app.visibility === 'unlisted' ? 'Hidden from the catalog; reachable by link' : 'Hidden from end users'}
      sx={{
        px: 0.9,
        py: 0.1,
        borderRadius: '6px',
        fontSize: 11.5,
        fontFamily: MONO,
        letterSpacing: '0.04em',
        color: app.visibility === 'unlisted' ? '#FCD34D' : '#F9A8D4',
        border: `1px solid ${app.visibility === 'unlisted' ? 'rgba(252,211,77,0.35)' : 'rgba(249,168,212,0.35)'}`,
        whiteSpace: 'nowrap',
      }}
    >
      {app.visibility === 'unlisted' ? 'Unlisted' : 'Admin only'}
    </Box>
  )
}

export function AlternativeTo({ app }: { app: GalleryApp }) {
  if (!app.replaces) return null
  return (
    <Typography sx={{ fontSize: 13, color: fg.faint, lineHeight: 1.5 }}>
      An alternative to {app.replaces}
    </Typography>
  )
}

export function NoResults({ q, onReset }: { q: string; onReset: () => void }) {
  return (
    <Box sx={{ py: 10, textAlign: 'center' }}>
      <Typography sx={{ fontFamily: DISPLAY, fontSize: 24 }}>No apps match “{q}”.</Typography>
      <Typography sx={{ mt: 1, color: fg.muted }}>
        Try another word, or{' '}
        <Box component="button" onClick={onReset} sx={{ color: accent.blue, background: 'none', border: 0, cursor: 'pointer', font: 'inherit', p: 0 }}>
          clear the filters
        </Box>
        .
      </Typography>
    </Box>
  )
}

function planLine(plans: { priceCents: number }[]): string {
  const paid = plans.map((p) => p.priceCents).filter((c) => c > 0)
  const parts = [
    plans.some((p) => p.priceCents === 0) && 'Free plan available',
    paid.length > 0 && `paid plans from ${formatEuro(Math.min(...paid))}/mo`,
  ].filter(Boolean) as string[]
  const line = parts.join(' · ')
  return line.charAt(0).toUpperCase() + line.slice(1)
}

/**
 * An expanded row's store content at a glance: screenshots, features and
 * plans, with install and a link to the full page.
 */
export function AppPreviewBody({ app, onInstall }: { app: GalleryApp; onInstall: (planId?: number) => void }) {
  const { screenshots, features, plans } = usePreview(app.id)
  const [shot, setShot] = useState<number | null>(null)

  return (
    <Stack spacing={3}>
      {screenshots.length > 0 && <ScreenshotStrip shots={screenshots} onOpen={setShot} height={{ xs: 150, md: 210 }} />}

      {features.length > 0 && (
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', md: '1fr 1fr 1fr' }, gap: 2.5 }}>
          {features.slice(0, 6).map((f, i) => (
            <Stack key={f.title} direction="row" spacing={1.5} sx={{ display: { xs: i >= 3 ? 'none' : 'flex', sm: 'flex' } }}>
              <FeatureIcon icon={f.icon} sx={{ fontSize: 20, color: fg.primary, mt: 0.25 }} />
              <Box sx={{ minWidth: 0 }}>
                <Typography sx={{ fontWeight: 600, fontSize: 14.5 }}>{f.title}</Typography>
                <Typography sx={{ color: fg.faint, fontSize: 13.5, lineHeight: 1.5, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                  {f.body}
                </Typography>
              </Box>
            </Stack>
          ))}
        </Box>
      )}

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ xs: 'stretch', sm: 'center' }}>
        <Typography sx={{ flex: 1, fontSize: 14, color: fg.muted }}>{planLine(plans)}</Typography>
        <Stack direction="row" spacing={1.5} alignItems="center">
          <InstallButton size="medium" onClick={() => onInstall()} sx={{ px: 2.5, py: 1, fontSize: 15, boxShadow: 'none', flex: { xs: 1, sm: 'none' } }}>
            Install
          </InstallButton>
          <Button component={RouterLink} to={app.href} endIcon={<ArrowForwardRounded />} sx={{ color: fg.muted, textTransform: 'none', fontSize: 15 }}>
            Full details
          </Button>
        </Stack>
      </Stack>

      <ScreenshotLightbox shots={screenshots} index={shot} onIndexChange={setShot} onClose={() => setShot(null)} />
    </Stack>
  )
}
