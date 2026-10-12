import { useCallback, useEffect, useRef } from 'react'
import { Box, Dialog, IconButton, Stack, Typography } from '@mui/material'
import CloseRoundedIcon from '@mui/icons-material/CloseRounded'
import ChevronLeftRoundedIcon from '@mui/icons-material/ChevronLeftRounded'
import ChevronRightRoundedIcon from '@mui/icons-material/ChevronRightRounded'
import { fg, MONO, SANS } from '../landing/landingTokens'
import type { Screenshot } from './listing'

interface ScreenshotLightboxProps {
  shots: Screenshot[]
  /** Index of the open shot, or null when closed. */
  index: number | null
  onIndexChange: (index: number) => void
  onClose: () => void
}

const navButtonSx = {
  width: 52,
  height: 52,
  color: fg.primary,
  background: 'rgba(255,255,255,0.08)',
  border: '1px solid rgba(255,255,255,0.12)',
  backdropFilter: 'blur(8px)',
  '&:hover': { background: 'rgba(255,255,255,0.16)' },
} as const

/**
 * Full-screen screenshot viewer: arrows, keyboard (←/→/Esc), swipe, and a
 * thumbnail rail to jump around — the pattern travel and app-store sites use.
 */
export function ScreenshotLightbox({ shots, index, onIndexChange, onClose }: ScreenshotLightboxProps) {
  const open = index !== null
  const current = index ?? 0
  const count = shots.length
  const swipeStart = useRef<number | null>(null)
  const railRef = useRef<HTMLDivElement | null>(null)

  const go = useCallback(
    (delta: number) => onIndexChange((current + delta + count) % count),
    [current, count, onIndexChange],
  )

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') go(-1)
      if (e.key === 'ArrowRight') go(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, go])

  useEffect(() => {
    railRef.current
      ?.querySelector<HTMLElement>(`[data-thumb="${current}"]`)
      ?.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' })
  }, [current, open])

  const shot = shots[current]

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullScreen
      slotProps={{
        paper: { sx: { background: 'rgba(5, 7, 14, 0.97)', backdropFilter: 'blur(6px)' } },
      }}
    >
      <Stack sx={{ height: '100%' }}>
        {/* Top bar */}
        <Stack direction="row" alignItems="center" sx={{ px: { xs: 2, md: 3 }, py: 1.5, gap: 2 }}>
          <Typography sx={{ fontFamily: MONO, fontSize: 13, color: fg.muted, letterSpacing: '0.08em' }}>
            {current + 1} / {count}
          </Typography>
          <Box sx={{ flex: 1, minWidth: 0, textAlign: 'center' }}>
            <Typography noWrap sx={{ fontFamily: SANS, fontSize: 15, color: fg.primary }}>
              {shot?.caption}
            </Typography>
            {shot?.credit && (
              <Typography noWrap sx={{ fontFamily: SANS, fontSize: 12, color: fg.faint, mt: 0.25 }}>
                {shot.credit.href ? (
                  <Box component="a" href={shot.credit.href} target="_blank" rel="noopener noreferrer" sx={{ color: 'inherit', '&:hover': { color: fg.muted } }}>
                    {shot.credit.text}
                  </Box>
                ) : (
                  shot.credit.text
                )}
              </Typography>
            )}
          </Box>
          <IconButton aria-label="Close" onClick={onClose} sx={{ color: fg.primary }}>
            <CloseRoundedIcon />
          </IconButton>
        </Stack>

        {/* Stage */}
        <Box
          sx={{ flex: 1, minHeight: 0, position: 'relative', display: 'grid', placeItems: 'center', px: { xs: 1, md: 12 } }}
          onPointerDown={(e) => {
            swipeStart.current = e.clientX
          }}
          onPointerUp={(e) => {
            if (swipeStart.current === null) return
            const dx = e.clientX - swipeStart.current
            swipeStart.current = null
            if (Math.abs(dx) > 50) go(dx < 0 ? 1 : -1)
          }}
        >
          {shot && (
            <Box
              key={shot.url}
              component="img"
              src={shot.url}
              alt={shot.caption}
              draggable={false}
              sx={{
                maxWidth: '100%',
                maxHeight: { xs: 'calc(100dvh - 170px)', md: 'calc(100dvh - 190px)' },
                objectFit: 'contain',
                borderRadius: '8px',
                boxShadow: '0 30px 80px rgba(0,0,0,0.6)',
                userSelect: 'none',
                animation: 'ap-fade 0.25s ease',
                '@keyframes ap-fade': { from: { opacity: 0 }, to: { opacity: 1 } },
              }}
            />
          )}
          <IconButton
            aria-label="Previous screenshot"
            onClick={() => go(-1)}
            sx={{ ...navButtonSx, position: 'absolute', left: { xs: 8, md: 28 }, display: { xs: 'none', sm: 'inline-flex' } }}
          >
            <ChevronLeftRoundedIcon fontSize="large" />
          </IconButton>
          <IconButton
            aria-label="Next screenshot"
            onClick={() => go(1)}
            sx={{ ...navButtonSx, position: 'absolute', right: { xs: 8, md: 28 }, display: { xs: 'none', sm: 'inline-flex' } }}
          >
            <ChevronRightRoundedIcon fontSize="large" />
          </IconButton>
        </Box>

        {/* Thumbnail rail */}
        <Stack
          ref={railRef}
          direction="row"
          spacing={1.25}
          sx={{
            px: 3,
            py: 2,
            overflowX: 'auto',
            justifyContent: { md: 'center' },
            scrollbarWidth: 'none',
            '&::-webkit-scrollbar': { display: 'none' },
          }}
        >
          {shots.map((s, i) => (
            <Box
              key={s.url}
              data-thumb={i}
              component="button"
              aria-label={`Show screenshot ${i + 1}`}
              onClick={() => onIndexChange(i)}
              sx={{
                flex: '0 0 auto',
                p: 0,
                height: 64,
                width: s.form === 'mobile' ? 34 : 104,
                borderRadius: '6px',
                overflow: 'hidden',
                cursor: 'pointer',
                border: i === current ? '2px solid #fff' : '2px solid transparent',
                opacity: i === current ? 1 : 0.45,
                background: 'none',
                transition: 'opacity 0.2s, border-color 0.2s',
                '&:hover': { opacity: 1 },
              }}
            >
              <Box component="img" src={s.thumbnailUrl} alt="" sx={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'top' }} />
            </Box>
          ))}
        </Stack>
      </Stack>
    </Dialog>
  )
}

export default ScreenshotLightbox
