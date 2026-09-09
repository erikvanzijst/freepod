import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef } from 'react'
import { Box } from '@mui/material'
import { fg, line, MONO, SANS } from '../landing/landingTokens'

const WORDS = ['photos', 'notes', 'files', 'vault', 'chat', 'blog', 'wiki', 'git', 'media', 'books', 'radio', 'drive']

export const HOME_SLOT = 'your app'

const ROW_HEIGHT = 48
const SPIN_MS = 2600

/** The tumbling names followed by the home slot: one lap always lands home. */
const UNIT = [...WORDS, HOME_SLOT]
const HOME_INDEX = WORDS.length
/** Three laps' worth, so the longest spin never runs off the end of the track. */
const STRIP = [...UNIT, ...UNIT, ...UNIT]

export interface AppNameReelHandle {
  spin: () => void
}

interface AppNameReelProps {
  /** Suppresses every animation, for `prefers-reduced-motion`. */
  reducedMotion?: boolean
  width?: number
}

export const AppNameReel = forwardRef<AppNameReelHandle, AppNameReelProps>(
  function AppNameReel({ reducedMotion = false, width = 108 }, ref) {
    const trackRef = useRef<HTMLDivElement | null>(null)
    const restIndexRef = useRef(HOME_INDEX)
    const spinningRef = useRef(false)
    const frameRef = useRef<number | null>(null)

    const place = useCallback((index: number) => {
      const track = trackRef.current
      if (track) track.style.transform = `translateY(${-(index * ROW_HEIGHT)}px)`
    }, [])

    const spin = useCallback(() => {
      if (reducedMotion || spinningRef.current || !trackRef.current) return
      spinningRef.current = true

      const from = restIndexRef.current
      const land = UNIT.length + HOME_INDEX
      const travel = land - from + UNIT.length
      const start = performance.now()

      const frame = (now: number) => {
        const t = Math.min(1, (now - start) / SPIN_MS)
        const eased = 1 - Math.pow(1 - t, 3)
        const position = from + travel * eased
        const track = trackRef.current
        if (track) track.style.transform = `translateY(${-(position * ROW_HEIGHT)}px)`
        if (t < 1) {
          frameRef.current = requestAnimationFrame(frame)
        } else {
          restIndexRef.current = land
          place(land)
          spinningRef.current = false
        }
      }
      frameRef.current = requestAnimationFrame(frame)
    }, [place, reducedMotion])

    useImperativeHandle(ref, () => ({ spin }), [spin])

    useEffect(() => {
      place(restIndexRef.current)
      return () => {
        if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
      }
    }, [place])

    return (
      <Box
        aria-hidden
        sx={{
          position: 'relative',
          width,
          flex: 'none',
          alignSelf: 'stretch',
          overflow: 'hidden',
          borderRight: `1px dashed ${line.soft}`,
          background: 'rgba(255,255,255,0.022)',
          maskImage: 'linear-gradient(180deg, transparent, #000 26%, #000 74%, transparent)',
          WebkitMaskImage: 'linear-gradient(180deg, transparent, #000 26%, #000 74%, transparent)',
        }}
      >
        <Box ref={trackRef} sx={{ position: 'absolute', top: 0, left: 0, right: 0, willChange: 'transform' }}>
          {STRIP.map((word, index) => (
            <Box
              component="b"
              key={`${word}-${index}`}
              sx={
                word === HOME_SLOT
                  ? {
                      display: 'block',
                      height: ROW_HEIGHT,
                      lineHeight: `${ROW_HEIGHT}px`,
                      textAlign: 'right',
                      pr: 1.25,
                      fontFamily: SANS,
                      fontStyle: 'italic',
                      fontSize: 15,
                      fontWeight: 400,
                      color: fg.faint,
                      opacity: 0.85,
                    }
                  : {
                      display: 'block',
                      height: ROW_HEIGHT,
                      lineHeight: `${ROW_HEIGHT}px`,
                      textAlign: 'right',
                      pr: 1.25,
                      fontFamily: MONO,
                      fontWeight: 400,
                      color: fg.faint,
                    }
              }
            >
              {word}
            </Box>
          ))}
        </Box>
      </Box>
    )
  },
)
