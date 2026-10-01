import { Box, Stack } from '@mui/material'
import { typedLength } from './timeline'

/** How long the browser scene plays before the demo is done. */
export const BROWSER_SCENE_MS = 5200

/** What the Node hello world really renders: a text/plain response. */
export function HelloPage() {
  return (
    <Box
      sx={{
        p: '1.2em',
        fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
        fontSize: 'clamp(13px, 2.2cqi, 18px)',
        color: '#111',
      }}
    >
      Hello, world!
    </Box>
  )
}

const LONG_URL = 'https://en.wikipedia.org/wiki/Digital_sovereignty#European_Union'
const TYPE_FROM = 700
const TYPE_TO = 2100
const PRESS_AT = 2450
const RESULT_AT = 2800

const existing = [
  { slug: 'q8Tz', url: 'github.com/erikvanzijst/freepod', hits: 41 },
  { slug: 'mN2a', url: 'news.ycombinator.com/item?id=4219…', hits: 17 },
]

/** The link shortener the agent "built": a URL gets typed in and shortened. */
export function LinksPage({ t }: { t: number }) {
  const typed = LONG_URL.slice(0, typedLength(LONG_URL, TYPE_FROM, TYPE_TO, t))
  const pressed = t >= PRESS_AT && t < PRESS_AT + 220
  const created = t >= RESULT_AT
  const rows = created ? [{ slug: 'k3x9', url: LONG_URL.replace('https://', ''), hits: 0 }, ...existing] : existing

  return (
    <Box
      sx={{
        height: '100%',
        fontFamily: 'system-ui, -apple-system, Segoe UI, sans-serif',
        fontSize: 'clamp(11px, 1.9cqi, 15px)',
        color: '#1E2235',
        background: 'linear-gradient(180deg, #F6F7FB, #fff 40%)',
        px: '2.2em',
        py: '1.6em',
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1} sx={{ fontWeight: 700, fontSize: '1.1em' }}>
        <Box
          sx={{
            width: '1.5em',
            height: '1.5em',
            borderRadius: '0.4em',
            background: 'linear-gradient(135deg, #6366F1, #EC4899)',
            color: '#fff',
            display: 'grid',
            placeItems: 'center',
            fontSize: '0.85em',
          }}
        >
          ↗
        </Box>
        <span>links</span>
      </Stack>

      <Box sx={{ mt: '1.4em', fontSize: '1.6em', fontWeight: 700, letterSpacing: '-0.02em' }}>
        Shorten a link
      </Box>

      <Stack direction="row" spacing={1} sx={{ mt: '0.9em' }}>
        <Box
          sx={{
            flex: 1,
            minWidth: 0,
            px: '0.9em',
            py: '0.6em',
            borderRadius: '0.5em',
            border: '1px solid #D5D9E6',
            background: '#fff',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            color: typed ? '#1E2235' : '#9AA1B5',
          }}
        >
          {typed || 'Paste a long URL…'}
        </Box>
        <Box
          sx={{
            px: '1.1em',
            py: '0.6em',
            borderRadius: '0.5em',
            fontWeight: 600,
            color: '#fff',
            background: pressed ? '#4338CA' : '#4F46E5',
            transform: pressed ? 'scale(0.96)' : 'none',
            transition: 'transform 0.1s, background 0.1s',
          }}
        >
          Shorten
        </Box>
      </Stack>

      <Box sx={{ mt: '1.2em', borderRadius: '0.6em', border: '1px solid #E4E7F0', overflow: 'hidden', background: '#fff' }}>
        {rows.map((row, i) => (
          <Stack
            key={row.slug}
            direction="row"
            alignItems="center"
            spacing={2}
            sx={{
              px: '0.9em',
              py: '0.55em',
              borderTop: i ? '1px solid #EEF0F5' : 'none',
              background: created && i === 0 ? '#EEF2FF' : 'transparent',
              transition: 'background 1.2s',
              animation: created && i === 0 ? 'lp-fade-up 0.5s cubic-bezier(0.22,1,0.36,1)' : 'none',
            }}
          >
            <Box sx={{ fontWeight: 600, color: '#4F46E5', whiteSpace: 'nowrap' }}>/{row.slug}</Box>
            <Box sx={{ flex: 1, minWidth: 0, color: '#6B7287', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {row.url}
            </Box>
            <Box sx={{ color: '#9AA1B5', whiteSpace: 'nowrap' }}>{row.hits} clicks</Box>
          </Stack>
        ))}
      </Box>
    </Box>
  )
}
