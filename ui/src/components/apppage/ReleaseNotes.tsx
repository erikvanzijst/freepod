import { useLayoutEffect, useRef, useState } from 'react'
import { Box, Dialog, DialogContent, IconButton, Stack, Typography } from '@mui/material'
import CloseRoundedIcon from '@mui/icons-material/CloseRounded'
import ExpandMoreRounded from '@mui/icons-material/ExpandMoreRounded'
import { accent, DISPLAY, fg, ink, line, MONO, SANS } from '../landing/landingTokens'
import { formatReleaseDate } from './listingFormat'
import { Markdown } from './Markdown'
import type { Release } from './listing'

/** Notes taller than this are folded behind "Show all changes". */
const FOLD_PX = 260


function VersionLine({ release, latest }: { release: Release; latest?: boolean }) {
  return (
    <Stack direction="row" alignItems="center" spacing={1.5}>
      <Typography sx={{ fontFamily: MONO, fontSize: 14, color: fg.primary }}>v{release.version}</Typography>
      {release.availableAt && (
        <Typography sx={{ fontSize: 13.5, color: fg.faint }}>{formatReleaseDate(release.availableAt)}</Typography>
      )}
      {latest && (
        <Typography sx={{ fontFamily: MONO, fontSize: 10, letterSpacing: '0.14em', color: accent.cyan, border: `1px solid ${accent.cyan}55`, px: 0.75, borderRadius: '4px' }}>
          CURRENT
        </Typography>
      )}
    </Stack>
  )
}

/**
 * "What's new": the version Freepod currently runs, its notes clamped to a few
 * lines, and the full history in a dialog.
 */
export function ReleaseNotes({ releases }: { releases: Release[] }) {
  const [expanded, setExpanded] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [overflows, setOverflows] = useState(false)
  const notesRef = useRef<HTMLDivElement | null>(null)
  const [latest] = releases

  useLayoutEffect(() => {
    const node = notesRef.current
    if (!node) return
    const observer = new ResizeObserver(() => setOverflows(node.scrollHeight > FOLD_PX))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  if (!latest) return null
  const folded = overflows && !expanded

  return (
    <Box>
      <Stack direction="row" alignItems="baseline" justifyContent="space-between" sx={{ mb: 2 }}>
        <Typography component="h2" sx={{ fontFamily: DISPLAY, fontWeight: 500, fontSize: { xs: 24, md: 28 }, letterSpacing: '-0.01em' }}>
          What’s new
        </Typography>
        <Box
          component="button"
          onClick={() => setHistoryOpen(true)}
          sx={{ p: 0, border: 0, background: 'none', cursor: 'pointer', color: accent.blue, fontFamily: SANS, fontSize: 15, fontWeight: 600 }}
        >
          Version history
        </Box>
      </Stack>
      <VersionLine release={latest} latest />
      <Box
        sx={{
          mt: 1.5,
          position: 'relative',
          maxHeight: folded ? FOLD_PX : 'none',
          overflow: 'hidden',
          ...(folded && {
            '&::after': { content: '""', position: 'absolute', inset: 'auto 0 0 0', height: 70, background: `linear-gradient(transparent, ${ink.base})` },
          }),
        }}
      >
        <Markdown boxRef={notesRef}>{latest.notes}</Markdown>
      </Box>
      {overflows && (
      <Box
        component="button"
        onClick={() => setExpanded((v) => !v)}
        sx={{ mt: 1, p: 0, border: 0, background: 'none', cursor: 'pointer', color: accent.blue, fontFamily: SANS, fontSize: 15, fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
      >
        {expanded ? 'Show less' : 'Show all changes'}
        <ExpandMoreRounded sx={{ fontSize: 20, transform: expanded ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
      </Box>
      )}

      <Dialog
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        maxWidth="sm"
        fullWidth
        slotProps={{ paper: { sx: { background: ink.raised, border: `1px solid ${line.soft}`, borderRadius: '20px' } } }}
      >
        <Stack direction="row" alignItems="center" sx={{ px: 3, pt: 2.5, pb: 1 }}>
          <Typography sx={{ flex: 1, fontFamily: DISPLAY, fontSize: 24 }}>Version history</Typography>
          <IconButton aria-label="Close" onClick={() => setHistoryOpen(false)} sx={{ color: fg.muted }}>
            <CloseRoundedIcon />
          </IconButton>
        </Stack>
        <DialogContent sx={{ px: 3, pb: 3 }}>
          <Stack divider={<Box sx={{ borderTop: `1px solid ${line.soft}`, my: 3 }} />}>
            {releases.map((r, i) => (
              <Box key={r.version}>
                <VersionLine release={r} latest={i === 0} />
                <Markdown sx={{ mt: 1.5 }}>{r.notes}</Markdown>
              </Box>
            ))}
          </Stack>
        </DialogContent>
      </Dialog>
    </Box>
  )
}

export default ReleaseNotes
