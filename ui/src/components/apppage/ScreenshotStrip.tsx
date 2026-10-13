import { useRef } from 'react'
import { Box, IconButton, Stack } from '@mui/material'
import type { ResponsiveStyleValue } from '@mui/system'
import ChevronLeftRounded from '@mui/icons-material/ChevronLeftRounded'
import ChevronRightRounded from '@mui/icons-material/ChevronRightRounded'
import { fg, line } from '../landing/landingTokens'
import type { Screenshot } from './listing'

/** Horizontally scrolling screenshot strip, App Store / Play Store style. */
interface ScreenshotStripProps {
  shots: Screenshot[]
  onOpen: (i: number) => void
  height?: ResponsiveStyleValue<number>
}

export function ScreenshotStrip({ shots, onOpen, height = { xs: 190, md: 340 } }: ScreenshotStripProps) {
  const ref = useRef<HTMLDivElement | null>(null)
  const scroll = (dir: number) => ref.current?.scrollBy({ left: dir * ref.current.clientWidth * 0.8, behavior: 'smooth' })
  const arrowSx = {
    position: 'absolute',
    top: '50%',
    transform: 'translateY(-50%)',
    zIndex: 2,
    width: 44,
    height: 44,
    color: fg.primary,
    background: 'rgba(11,16,32,0.8)',
    border: `1px solid ${line.soft}`,
    backdropFilter: 'blur(8px)',
    opacity: 0,
    transition: 'opacity 0.2s',
    display: { xs: 'none', md: 'inline-flex' },
    '&:hover': { background: 'rgba(11,16,32,0.95)' },
  } as const

  return (
    <Box sx={{ position: 'relative', '&:hover .ap-arrow': { opacity: 1 } }}>
      <IconButton className="ap-arrow" aria-label="Scroll left" onClick={() => scroll(-1)} sx={{ ...arrowSx, left: -22 }}>
        <ChevronLeftRounded />
      </IconButton>
      <Stack
        ref={ref}
        direction="row"
        spacing={2}
        sx={{
          overflowX: 'auto',
          scrollSnapType: 'x mandatory',
          pb: 1,
          scrollbarWidth: 'none',
          '&::-webkit-scrollbar': { display: 'none' },
        }}
      >
        {shots.map((shot, i) => (
          <Box
            key={shot.url}
            component="button"
            onClick={() => onOpen(i)}
            aria-label={`Open screenshot: ${shot.caption}`}
            sx={{
              flex: '0 0 auto',
              p: 0,
              height,
              aspectRatio: shot.form === 'mobile' ? '390 / 844' : '16 / 10',
              borderRadius: '12px',
              overflow: 'hidden',
              cursor: 'zoom-in',
              border: `1px solid ${line.soft}`,
              background: '#000',
              scrollSnapAlign: 'start',
              transition: 'border-color 0.2s, transform 0.2s',
              '&:hover': { borderColor: 'rgba(148,163,184,0.45)' },
            }}
          >
            <Box component="img" src={shot.thumbnailUrl} alt="" loading="lazy" sx={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'top' }} />
          </Box>
        ))}
      </Stack>
      <IconButton className="ap-arrow" aria-label="Scroll right" onClick={() => scroll(1)} sx={{ ...arrowSx, right: -22 }}>
        <ChevronRightRounded />
      </IconButton>
    </Box>
  )
}

export default ScreenshotStrip
