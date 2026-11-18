import { useEffect, useState } from 'react'
import { Box, Stack } from '@mui/material'

const reducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** Milliseconds of free-running time while `running`; frozen at 0 with reduced motion. */
function useLoopTime(running: boolean): number {
  const [t, setT] = useState(0)

  useEffect(() => {
    if (!running || reducedMotion()) return
    let frame = 0
    let last = performance.now()
    const tick = (now: number) => {
      const dt = Math.min(now - last, 100)
      last = now
      setT((prev) => prev + dt)
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [running])

  return t
}

/** Triangle wave: 0 → 1 → 0 over one period. */
const tri = (p: number) => {
  const f = p - Math.floor(p)
  return f < 0.5 ? f * 2 : 2 - f * 2
}

const X_PERIOD = 2600
const Y_PERIOD = 1700
const PADDLE = 0.24

const ballX = (t: number) => 0.055 + tri(t / X_PERIOD) * 0.89
const ballY = (t: number) => 0.05 + tri(t / Y_PERIOD + 0.2) * 0.9
const paddle = (t: number, lag: number) =>
  Math.min(1 - PADDLE / 2, Math.max(PADDLE / 2, ballY(Math.max(0, t - lag))))

const pct = (v: number) => `${(v * 100).toFixed(2)}%`

const levels = ['EASY', 'NORMAL', 'HARD']
const highScores: [string, string][] = [
  ['ADA', '5 – 2'],
  ['LIN', '5 – 3'],
  ['MAX', '5 – 4'],
  ['SAM', '4 – 5'],
]

/** In a short preview the game field keeps its shape and the rest of the page goes. */
const whenShort = { '@container (max-height: 360px)': { display: 'none' } }

const neonPink = '#FF4FD8'
const neonCyan = '#3BF0FF'

/**
 * The game App Studio "builds" in the landing demo: a Pong rally driven purely
 * by time, first plain and then, after the second prompt, restyled neon.
 */
export function StudioPong({ running, neon }: { running: boolean; neon: boolean }) {
  const t = useLoopTime(running)
  const crossings = Math.floor(t / (X_PERIOD / 2))
  const you = Math.floor(crossings / 3) % 5
  const cpu = Math.floor((crossings + 1) / 4) % 5
  const fade = 'color 0.8s, background 0.8s, box-shadow 0.8s, border-color 0.8s, text-shadow 0.8s'

  const paddleSx = (side: 'left' | 'right', y: number) => ({
    position: 'absolute' as const,
    [side]: '2.5%',
    top: pct(y - PADDLE / 2),
    width: '2%',
    height: pct(PADDLE),
    borderRadius: neon ? '0.4em' : 0,
    background: neon ? (side === 'left' ? neonCyan : neonPink) : '#E8E8E8',
    boxShadow: neon ? `0 0 0.8em ${side === 'left' ? neonCyan : neonPink}` : 'none',
    transition: fade,
  })

  return (
    <Stack
      sx={{
        height: '100%',
        p: '0.9em',
        gap: '0.75em',
        containerType: 'inline-size',
        fontFamily: "'Space Mono', ui-monospace, monospace",
        background: neon ? 'radial-gradient(120% 90% at 50% 0%, #2A0B45, #07030F 70%)' : '#0A0A0A',
        transition: fade,
      }}
    >
      <Stack direction="row" alignItems="baseline" justifyContent="space-between" sx={{ px: '0.3em' }}>
        <Box
          sx={{
            fontWeight: 700,
            letterSpacing: '0.3em',
            fontSize: '1.15em',
            color: neon ? neonPink : '#E8E8E8',
            textShadow: neon ? `0 0 0.6em ${neonPink}` : 'none',
            transition: fade,
          }}
        >
          PONG
        </Box>
        <Box sx={{ fontSize: '0.75em', color: neon ? '#B79BD8' : '#8A8A8A', transition: fade }}>
          {neon ? 'FIRST TO 5' : '↑ ↓ TO MOVE'}
        </Box>
      </Stack>

      <Box
        sx={{
          position: 'relative',
          flex: '0 1 calc((100cqi - 1.8em) * 0.75)',
          minHeight: 0,
          border: `1px solid ${neon ? 'rgba(59,240,255,0.35)' : '#2A2A2A'}`,
          borderRadius: neon ? '0.6em' : 0,
          boxShadow: neon ? 'inset 0 0 2.5em rgba(255,79,216,0.18)' : 'none',
          overflow: 'hidden',
          transition: fade,
        }}
      >
        <Box
          sx={{
            position: 'absolute',
            left: '50%',
            top: '4%',
            bottom: '4%',
            borderLeft: `2px dashed ${neon ? 'rgba(183,155,216,0.45)' : '#3A3A3A'}`,
            transition: fade,
          }}
        />
        <Stack
          direction="row"
          justifyContent="center"
          spacing="2.4em"
          sx={{
            position: 'absolute',
            inset: '6% 0 auto',
            fontSize: '2em',
            fontWeight: 700,
            color: neon ? 'rgba(255,255,255,0.85)' : '#5A5A5A',
            textShadow: neon ? `0 0 0.4em ${neonCyan}` : 'none',
            transition: fade,
          }}
        >
          <span>{you}</span>
          <span>{cpu}</span>
        </Stack>
        <Box sx={paddleSx('left', paddle(t, 90))} />
        <Box sx={paddleSx('right', paddle(t, 260))} />
        <Box
          sx={{
            position: 'absolute',
            left: pct(ballX(t)),
            top: pct(ballY(t)),
            width: '0.7em',
            height: '0.7em',
            transform: 'translate(-50%, -50%)',
            borderRadius: neon ? '50%' : 0,
            background: neon ? '#fff' : '#E8E8E8',
            boxShadow: neon ? `0 0 0.9em ${neonPink}, 0 0 0.3em #fff` : 'none',
            transition: fade,
          }}
        />
      </Box>

      <Stack direction="row" spacing="0.5em" sx={{ flexShrink: 0, fontSize: '0.75em', ...whenShort }}>
        {levels.map((level) => {
          const selected = level === 'NORMAL'
          return (
            <Box
              key={level}
              sx={{
                flex: 1,
                py: '0.45em',
                textAlign: 'center',
                letterSpacing: '0.15em',
                border: '1px solid',
                borderRadius: neon ? '0.5em' : 0,
                borderColor: selected ? (neon ? neonCyan : '#E8E8E8') : neon ? 'rgba(183,155,216,0.3)' : '#2A2A2A',
                color: selected ? (neon ? neonCyan : '#E8E8E8') : neon ? '#B79BD8' : '#6A6A6A',
                boxShadow: selected && neon ? `0 0 0.8em rgba(59,240,255,0.35)` : 'none',
                transition: fade,
              }}
            >
              {level}
            </Box>
          )
        })}
      </Stack>

      <Box
        sx={{
          flex: '1 1 0',
          minHeight: 0,
          overflow: 'hidden',
          ...whenShort,
          px: '0.9em',
          py: '0.7em',
          fontSize: '0.78em',
          border: `1px solid ${neon ? 'rgba(255,79,216,0.25)' : '#2A2A2A'}`,
          borderRadius: neon ? '0.6em' : 0,
          transition: fade,
        }}
      >
        <Box
          sx={{
            mb: '0.5em',
            letterSpacing: '0.25em',
            color: neon ? neonPink : '#8A8A8A',
            textShadow: neon ? `0 0 0.5em ${neonPink}` : 'none',
            transition: fade,
          }}
        >
          HIGH SCORES
        </Box>
        {highScores.map(([name, score], i) => (
          <Stack
            key={name}
            direction="row"
            justifyContent="space-between"
            sx={{ py: '0.2em', color: neon ? (i ? '#D8C8F0' : neonCyan) : i ? '#8A8A8A' : '#E8E8E8', transition: fade }}
          >
            <span>
              {i + 1}. {name}
            </span>
            <span>{score}</span>
          </Stack>
        ))}
      </Box>
    </Stack>
  )
}

export default StudioPong
