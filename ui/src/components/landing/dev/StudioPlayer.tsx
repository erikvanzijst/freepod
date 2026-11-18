import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Box, Button, Stack } from '@mui/material'
import ReplayRoundedIcon from '@mui/icons-material/ReplayRounded'
import LockRoundedIcon from '@mui/icons-material/LockRounded'
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded'
import { accent, fg, SANS } from '../landingTokens'
import { spinnerFrame, typedLength } from './timeline'
import { useDemoClock } from './useDemoClock'
import { WindowFrame } from './DemoPlayer'
import StudioPong from './StudioPong'

type Item =
  | { kind: 'user'; text: string; typeFrom: number; at: number }
  | { kind: 'say'; at: number; text: ReactNode }
  | { kind: 'tool'; at: number; done: number; name: string; args: string; result: string; ok?: boolean }

const APP_URL = 'pong-ada.freepod.app'

const script: Item[] = [
  { kind: 'user', text: 'Make a Pong game I can play against the computer', typeFrom: 700, at: 2500 },
  { kind: 'say', at: 2900, text: 'On it: Pong, you against the computer.' },
  { kind: 'tool', at: 3300, done: 4600, name: 'Write', args: 'index.html  game.js  style.css', result: '+214', ok: true },
  { kind: 'tool', at: 4800, done: 5600, name: 'Shell', args: 'dev-app', result: 'running' },
  { kind: 'say', at: 5900, text: "It's in the preview. Use ↑ and ↓ to play." },
  { kind: 'user', text: 'Make it neon, and first to 5 wins', typeFrom: 7600, at: 8900 },
  { kind: 'tool', at: 9300, done: 10300, name: 'Edit', args: 'style.css  game.js', result: '+38 −12', ok: true },
  { kind: 'say', at: 10600, text: 'Done: neon glow, and the first to 5 wins.' },
  { kind: 'user', text: 'Deploy please', typeFrom: 12000, at: 12800 },
  { kind: 'tool', at: 13000, done: 15000, name: 'Shell', args: 'freepod deploy', result: '✓ released in 41s', ok: true },
  {
    kind: 'say',
    at: 15300,
    text: (
      <>
        Pong is live at{' '}
        <Box component="span" sx={{ color: accent.blue, textDecoration: 'underline', textUnderlineOffset: '0.2em', whiteSpace: 'nowrap' }}>
          https://{APP_URL}
        </Box>
      </>
    ),
  },
]

const PREVIEW_AT = 5600
const NEON_AT = 10300
const DEPLOYED_AT = 15300
const TOTAL = 17500

/** Each prompt keeps the agent busy until the last item before the next prompt. */
const busySpans = script.flatMap((item, i) => {
  if (item.kind !== 'user') return []
  const next = script.findIndex((other, j) => j > i && other.kind === 'user')
  const turn = script.slice(i + 1, next === -1 ? undefined : next)
  return [[item.at, turn.at(-1)?.at ?? item.at] as const]
})

const busy = (t: number) => busySpans.some(([from, to]) => t >= from && t < to)

function Spinner({ t }: { t: number }) {
  return (
    <Box component="span" sx={{ color: accent.cyan, fontFamily: 'ui-monospace, monospace' }}>
      {spinnerFrame(t)}
    </Box>
  )
}

function ChatItem({ item, t }: { item: Item; t: number }) {
  const enter = { animation: 'lp-fade-up 0.45s cubic-bezier(0.22,1,0.36,1)' }

  if (item.kind === 'user') {
    return (
      <Box
        sx={{
          ...enter,
          alignSelf: 'flex-end',
          maxWidth: '85%',
          px: '0.85em',
          py: '0.5em',
          borderRadius: '0.7em',
          background: 'rgba(255,255,255,0.08)',
          color: fg.primary,
        }}
      >
        {item.text}
      </Box>
    )
  }

  if (item.kind === 'say') {
    return <Box sx={{ ...enter, color: fg.primary }}>{item.text}</Box>
  }

  const running = t < item.done
  return (
    <Stack direction="row" spacing="0.6em" alignItems="baseline" sx={{ ...enter, whiteSpace: 'nowrap', minWidth: 0 }}>
      <Box component="span" sx={{ fontWeight: 600, color: running ? fg.muted : fg.primary }}>
        {item.name}
      </Box>
      <Box component="span" sx={{ color: fg.faint, overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0 }}>
        {item.args}
      </Box>
      {running ? (
        <Spinner t={t} />
      ) : (
        <Box component="span" sx={{ color: item.ok ? '#5EEAD4' : fg.faint, flexShrink: 0 }}>
          {item.result}
        </Box>
      )}
    </Stack>
  )
}

function Composer({ t }: { t: number }) {
  const typing = script.find((item) => item.kind === 'user' && t >= item.typeFrom && t < item.at)
  const text =
    typing?.kind === 'user' ? typing.text.slice(0, typedLength(typing.text, typing.typeFrom, typing.at - 250, t)) : ''

  return (
    <Box
      sx={{
        mt: '0.8em',
        px: '0.85em',
        pt: '0.6em',
        pb: '0.45em',
        borderRadius: '0.7em',
        border: '1px solid rgba(148, 163, 184, 0.22)',
        background: 'rgba(255,255,255,0.025)',
      }}
    >
      <Box sx={{ minHeight: '1.5em', whiteSpace: 'nowrap', overflow: 'hidden', color: text ? fg.primary : fg.faint }}>
        {text || 'Describe the app you want…'}
        {typing && (
          <Box
            component="span"
            sx={{ display: 'inline-block', width: '1px', height: '1.1em', ml: '1px', verticalAlign: 'text-bottom', background: fg.primary }}
          />
        )}
      </Box>
      <Stack direction="row" justifyContent="space-between" sx={{ mt: '0.35em', fontSize: '0.82em', color: fg.faint }}>
        <span>Free model ⌄</span>
        <span>↵</span>
      </Stack>
    </Box>
  )
}

function Preview({ t, running }: { t: number; running: boolean }) {
  const live = t >= PREVIEW_AT
  const deployed = t >= DEPLOYED_AT

  return (
    <Box
      sx={{
        position: 'relative',
        height: '100%',
        containerType: 'size',
        borderRadius: '0.6em',
        overflow: 'hidden',
        border: '1px solid rgba(255,255,255,0.08)',
        background: '#0A0A0A',
      }}
    >
      {live ? (
        <Box sx={{ height: '100%', animation: 'lp-fade-up 0.5s cubic-bezier(0.22,1,0.36,1)' }}>
          <StudioPong running={running} neon={t >= NEON_AT} />
        </Box>
      ) : (
        <Stack alignItems="center" justifyContent="center" spacing="0.6em" sx={{ height: '100%', color: fg.faint }}>
          <Box sx={{ width: '1.6em', height: '1.6em', borderRadius: '50%', border: `2px solid ${fg.faint}`, opacity: 0.5 }} />
          <span>Waiting for your app…</span>
        </Stack>
      )}

      <Stack
        direction="row"
        alignItems="center"
        spacing="0.5em"
        sx={{
          position: 'absolute',
          left: '50%',
          bottom: '0.9em',
          px: '0.9em',
          py: '0.45em',
          borderRadius: 999,
          whiteSpace: 'nowrap',
          fontSize: '0.88em',
          color: '#0B1020',
          fontWeight: 600,
          background: '#5EEAD4',
          boxShadow: '0 10px 30px rgba(0,0,0,0.45)',
          transition: 'opacity 0.5s, transform 0.5s cubic-bezier(0.22,1,0.36,1)',
          opacity: deployed ? 1 : 0,
          transform: deployed ? 'translate(-50%, 0)' : 'translate(-50%, 1.5em)',
        }}
      >
        <span>✓ Deployed</span>
        <Box component="span" sx={{ fontWeight: 500, opacity: 0.8 }}>
          {APP_URL}
        </Box>
      </Stack>
    </Box>
  )
}

function StudioScene({ running, onReplay }: { running: boolean; onReplay: () => void }) {
  const t = useDemoClock(TOTAL, running)
  const visible = script.filter((item) => t >= item.at)
  const done = t >= TOTAL
  const live = t >= PREVIEW_AT

  return (
    <>
      <WindowFrame
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
            <Box component="span" sx={{ whiteSpace: 'nowrap' }}>studio-ada.freepod.app</Box>
          </Stack>
        }
      >
        <Box sx={{ fontFamily: SANS, fontSize: 'clamp(11.5px, 2.05cqi, 15px)', lineHeight: 1.5, color: fg.primary }}>
          <Stack
            direction="row"
            alignItems="center"
            justifyContent="space-between"
            sx={{ px: '1.1em', py: '0.6em', borderBottom: '1px solid rgba(255,255,255,0.07)' }}
          >
            <Stack direction="row" spacing="0.5em" alignItems="center">
              <Box sx={{ color: fg.faint }}>Freepod</Box>
              <Box sx={{ color: fg.faint, opacity: 0.6 }}>/</Box>
              <Box sx={{ fontWeight: 600 }}>App Studio</Box>
            </Stack>
            <Stack
              direction="row"
              alignItems="center"
              spacing="0.45em"
              sx={{
                px: '0.75em',
                py: '0.25em',
                borderRadius: '0.5em',
                border: '1px solid rgba(255,255,255,0.12)',
                color: live ? fg.primary : fg.faint,
                transition: 'color 0.4s',
              }}
            >
              <Box
                sx={{
                  width: '0.55em',
                  height: '0.55em',
                  borderRadius: '50%',
                  background: live ? '#22C55E' : 'rgba(255,255,255,0.25)',
                  boxShadow: live ? '0 0 0.6em #22C55E' : 'none',
                  transition: 'background 0.4s, box-shadow 0.4s',
                }}
              />
              <span>Preview</span>
              <OpenInNewRoundedIcon sx={{ fontSize: '1em' }} />
            </Stack>
          </Stack>

          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: '9fr 11fr',
              gap: '0.9em',
              p: '0.9em',
              height: 'clamp(340px, 79cqi, 560px)',
              '@container (max-width: 560px)': {
                gridTemplateColumns: '1fr',
                gridTemplateRows: '58% 1fr',
                height: 'clamp(500px, 160cqi, 640px)',
              },
            }}
          >
            <Stack sx={{ minHeight: 0, px: '0.3em', '@container (max-width: 560px)': { order: 2 } }}>
              <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ pb: '0.6em', color: fg.muted }}>
                <Box sx={{ fontWeight: 600, color: visible.length ? fg.primary : fg.faint }}>
                  {visible.length ? 'Pong against the computer' : 'New session'}
                </Box>
                {busy(t) && <Spinner t={t} />}
              </Stack>
              <Box
                sx={{
                  flex: 1,
                  minHeight: 0,
                  overflow: 'hidden',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'flex-end',
                  maskImage: 'linear-gradient(to bottom, transparent, #000 1.5em)',
                }}
              >
                <Stack spacing="0.75em" sx={{ mb: 'auto' }}>
                  {visible.map((item, i) => (
                    <ChatItem key={i} item={item} t={t} />
                  ))}
                </Stack>
              </Box>
              <Composer t={t} />
            </Stack>

            <Preview t={t} running={running} />
          </Box>
        </Box>
      </WindowFrame>

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

/**
 * App Studio building, restyling and deploying a Pong game, played as a fake
 * browser window: the conversation beside the live preview. Starts when
 * scrolled into view and pauses when scrolled away.
 */
export function StudioPlayer() {
  const ref = useRef<HTMLDivElement | null>(null)
  const [inView, setInView] = useState(false)
  const [run, setRun] = useState(0)

  useEffect(() => {
    const node = ref.current
    if (!node) return
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { threshold: 0.35 })
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return (
    <Box ref={ref} sx={{ position: 'relative', containerType: 'inline-size' }}>
      <StudioScene key={run} running={inView} onReplay={() => setRun((n) => n + 1)} />
    </Box>
  )
}

export default StudioPlayer
