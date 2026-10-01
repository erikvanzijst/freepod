import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Box, Button, Stack } from '@mui/material'
import ReplayRoundedIcon from '@mui/icons-material/ReplayRounded'
import LockRoundedIcon from '@mui/icons-material/LockRounded'
import { accent, fg, MONO, SANS } from '../landingTokens'
import { compile, spinnerFrame, typedLength, type Compiled, type Line, type Seg, type Tone } from './timeline'
import { useDemoClock } from './useDemoClock'
import type { Demo } from './demos'
import { HelloPage, LinksPage, BROWSER_SCENE_MS } from './DemoApps'

const toneColor: Record<Tone, string> = {
  fg: fg.primary,
  muted: fg.muted,
  dim: fg.faint,
  ok: '#5EEAD4',
  link: accent.blue,
  prompt: accent.pink,
  accent: accent.cyan,
  warn: '#FBBF24',
}

/** Gap between the terminal finishing and the browser sliding in. */
const BROWSER_DELAY = 700
const ROWS = 18

function Segs({ segs }: { segs: Seg[] }) {
  return (
    <>
      {segs.map(([text, tone = 'fg'], i) => (
        <Box
          key={i}
          component="span"
          sx={{
            color: toneColor[tone],
            ...(tone === 'link' && { textDecoration: 'underline', textUnderlineOffset: '0.2em' }),
          }}
        >
          {text}
        </Box>
      ))}
    </>
  )
}

function Cursor({ blink }: { blink: boolean }) {
  return (
    <Box
      component="span"
      sx={{
        display: 'inline-block',
        width: '0.6em',
        height: '1.15em',
        verticalAlign: 'text-bottom',
        background: fg.primary,
        opacity: 0.85,
        animation: blink ? 'lp-cursor 1.05s steps(1) infinite' : 'none',
      }}
    />
  )
}

function TerminalLine({ line, t, cursor }: { line: Line; t: number; cursor: boolean }) {
  if (line.task) {
    const running = t < line.task.until
    return (
      <div>
        {running ? (
          <>
            <Box component="span" sx={{ color: accent.cyan }}>
              {spinnerFrame(t)}{' '}
            </Box>
            <Segs segs={line.segs ?? []} />
          </>
        ) : (
          <Segs segs={line.task.done} />
        )}
      </div>
    )
  }
  const typed = line.typed
  return (
    <div>
      <Segs segs={line.prefix} />
      {line.segs && <Segs segs={line.segs} />}
      {typed && (
        <Box component="span" sx={{ color: toneColor[typed.tone ?? 'fg'] }}>
          {typed.text.slice(0, typedLength(typed.text, line.start, typed.end, t))}
        </Box>
      )}
      {cursor && <Cursor blink={!typed || t >= typed.end} />}
    </div>
  )
}

/** Shared macOS-ish window chrome for the terminal and the browser. */
function WindowFrame({ title, children, light }: { title: ReactNode; children: ReactNode; light?: boolean }) {
  return (
    <Box
      sx={{
        borderRadius: '12px',
        overflow: 'hidden',
        border: '1px solid rgba(255,255,255,0.1)',
        background: light ? '#fff' : 'rgba(9, 13, 26, 0.92)',
        boxShadow: '0 40px 90px rgba(3, 6, 16, 0.7), 0 0 0 1px rgba(0,0,0,0.4)',
        backdropFilter: 'blur(12px)',
      }}
    >
      <Stack
        direction="row"
        alignItems="center"
        sx={{
          height: 40,
          px: 2,
          gap: 1.5,
          background: light ? '#1A2036' : 'rgba(255,255,255,0.035)',
          borderBottom: '1px solid rgba(255,255,255,0.07)',
        }}
      >
        <Stack direction="row" spacing={0.9}>
          {['#FF5F57', '#FEBC2E', '#28C840'].map((c) => (
            <Box key={c} sx={{ width: 12, height: 12, borderRadius: '50%', background: c, opacity: 0.85 }} />
          ))}
        </Stack>
        <Box sx={{ flex: 1, minWidth: 0, display: 'flex', justifyContent: 'center', pr: 6 }}>{title}</Box>
      </Stack>
      {children}
    </Box>
  )
}

function workingFooter(compiled: Compiled, t: number) {
  const start = compiled.marks['work-start']
  const end = compiled.marks['work-end']
  if (start === undefined || end === undefined || t < start) return null
  // The run is sped up roughly 8x; the footer reports the "real" duration.
  const secs = Math.floor(((Math.min(t, end) - start) / 1000) * 8.4)
  const clock = secs >= 60 ? `${Math.floor(secs / 60)}m ${String(secs % 60).padStart(2, '0')}s` : `${secs}s`
  return t < end ? (
    <>
      <Box component="span" sx={{ color: accent.pink }}>✻ </Box>
      <Box component="span" sx={{ color: fg.muted }}>Working… </Box>
      <Box component="span" sx={{ color: fg.faint }}>{clock} · esc to interrupt</Box>
    </>
  ) : (
    <Box component="span" sx={{ color: fg.faint }}>✓ Done in {clock}</Box>
  )
}

function Terminal({ demo, compiled, t }: { demo: Demo; compiled: Compiled; t: number }) {
  const visible = compiled.lines.filter((line) => line.start <= t)
  const input = compiled.input
  const typingInput = input && t >= input.start && t < input.end + 520
  const inputText = input && typingInput ? input.text.slice(0, typedLength(input.text, input.start, input.end, t)) : ''

  return (
    <WindowFrame
      title={
        <Box component="span" sx={{ fontFamily: MONO, fontSize: 12.5, color: fg.faint }}>
          {demo.windowTitle}
        </Box>
      }
    >
      <Box
        sx={{
          fontFamily: MONO,
          fontSize: 'clamp(10.5px, 2.4cqi, 17px)',
          lineHeight: 1.65,
          color: fg.primary,
          px: '1.4em',
          py: '1.1em',
          whiteSpace: 'pre',
        }}
      >
        <Box
          sx={{
            height: `${(demo.tui ? ROWS - 4 : ROWS) * 1.65}em`,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'flex-end',
          }}
        >
          {/* Auto margin fills top-down; once lines overflow it collapses and
              flex-end keeps the newest line in view, like a scrolling terminal. */}
          <Box sx={{ mb: 'auto' }}>
            {visible.map((line, i) => (
              <TerminalLine
                key={i}
                line={line}
                t={t}
                cursor={!demo.tui && i === visible.length - 1 && Boolean(line.typed)}
              />
            ))}
          </Box>
        </Box>

        {demo.tui && (
          <>
            <Box
              sx={{
                mt: '0.6em',
                px: '0.8em',
                py: '0.35em',
                border: '1px solid rgba(148, 163, 184, 0.28)',
                borderRadius: '0.5em',
              }}
            >
              <Box component="span" sx={{ color: accent.pink }}>❯ </Box>
              {inputText || !input || t < input.start ? (
                <Box component="span">{inputText}</Box>
              ) : null}
              {!inputText && (!input || t < input.start) && (
                <Box component="span" sx={{ color: fg.faint }}>Describe what to build…</Box>
              )}
              <Cursor blink={!typingInput} />
            </Box>
            <Box sx={{ mt: '0.35em', px: '0.2em', fontSize: '0.8em', minHeight: '1.65em' }}>
              {workingFooter(compiled, t)}
            </Box>
          </>
        )}
      </Box>
    </WindowFrame>
  )
}

function Browser({ demo, bt }: { demo: Demo; bt: number }) {
  const loading = Math.min(1, bt / 650)
  return (
    <WindowFrame
      light
      title={
        <Stack
          direction="row"
          alignItems="center"
          spacing={0.75}
          sx={{
            px: 1.5,
            py: 0.5,
            width: '100%',
            maxWidth: 420,
            borderRadius: 999,
            background: 'rgba(255,255,255,0.07)',
            fontFamily: SANS,
            fontSize: 13.5,
            color: fg.primary,
            overflow: 'hidden',
          }}
        >
          <LockRoundedIcon sx={{ fontSize: 13, color: fg.muted }} />
          <Box component="span" sx={{ whiteSpace: 'nowrap' }}>{demo.url}</Box>
        </Stack>
      }
    >
      <Box sx={{ position: 'relative', height: 'clamp(240px, 52cqi, 420px)', background: '#fff' }}>
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            height: 3,
            width: `${loading * 100}%`,
            opacity: loading < 1 ? 1 : 0,
            background: `linear-gradient(90deg, ${accent.blueDeep}, ${accent.magenta})`,
            transition: 'opacity 0.3s',
          }}
        />
        <Box sx={{ height: '100%', opacity: bt > 550 ? 1 : 0, transition: 'opacity 0.35s' }}>
          {demo.id === 'manual' ? <HelloPage /> : <LinksPage t={bt - 550} />}
        </Box>
      </Box>
    </WindowFrame>
  )
}

/**
 * Plays one demo: the terminal session, then a browser window sliding over it
 * with the app live on its hostname. Starts when scrolled into view and pauses
 * when scrolled away; Replay remounts the scene to restart it.
 */
export function DemoPlayer({ demo }: { demo: Demo }) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [inView, setInView] = useState(false)
  const [run, setRun] = useState(0)

  useEffect(() => {
    const node = ref.current
    if (!node) return
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), {
      threshold: 0.35,
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return (
    <Box ref={ref} sx={{ position: 'relative', containerType: 'inline-size', pb: { xs: 0, md: 6 } }}>
      <DemoScene key={run} demo={demo} running={inView} onReplay={() => setRun((n) => n + 1)} />
    </Box>
  )
}

function DemoScene({ demo, running, onReplay }: { demo: Demo; running: boolean; onReplay: () => void }) {
  const compiled = useMemo(() => compile(demo.steps), [demo])
  const browserStart = compiled.total + BROWSER_DELAY
  const t = useDemoClock(browserStart + BROWSER_SCENE_MS, running)
  const showBrowser = t >= browserStart
  const done = t >= browserStart + BROWSER_SCENE_MS

  return (
    <>
      <Box
        sx={{
          transition: 'opacity 0.6s, transform 0.6s',
          opacity: showBrowser ? 0.45 : 1,
          transform: showBrowser ? 'scale(0.97)' : 'none',
          transformOrigin: 'top left',
        }}
      >
        <Terminal demo={demo} compiled={compiled} t={t} />
      </Box>

      <Box
        aria-hidden={!showBrowser}
        sx={{
          position: 'absolute',
          left: { xs: '4%', md: '14%' },
          right: { xs: '4%', md: '-4%' },
          bottom: { xs: '-6%', md: 0 },
          transition: 'opacity 0.6s cubic-bezier(0.22,1,0.36,1), transform 0.7s cubic-bezier(0.22,1,0.36,1)',
          opacity: showBrowser ? 1 : 0,
          transform: showBrowser ? 'none' : 'translate3d(0, 40px, 0) scale(0.97)',
          pointerEvents: showBrowser ? 'auto' : 'none',
        }}
      >
        <Browser demo={demo} bt={Math.max(0, t - browserStart)} />
      </Box>

      <Button
        onClick={onReplay}
        startIcon={<ReplayRoundedIcon />}
        size="small"
        sx={{
          position: 'absolute',
          top: -44,
          right: 0,
          borderRadius: 999,
          px: 1.75,
          color: fg.muted,
          fontFamily: SANS,
          border: '1px solid rgba(255,255,255,0.12)',
          opacity: done ? 1 : 0,
          pointerEvents: done ? 'auto' : 'none',
          transition: 'opacity 0.4s',
          '&:hover': { color: fg.primary, background: 'rgba(255,255,255,0.06)' },
        }}
      >
        Replay
      </Button>
    </>
  )
}

export default DemoPlayer
