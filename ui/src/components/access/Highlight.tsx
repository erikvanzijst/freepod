import { Box } from '@mui/material'

/** `text` with each case-insensitive occurrence of `query` marked. */
export function Highlight({ text, query }: { text: string; query: string }) {
  const q = query.trim().toLowerCase()
  if (!q) return <>{text}</>
  const parts: React.ReactNode[] = []
  const lower = text.toLowerCase()
  let at = 0
  for (let i = lower.indexOf(q); i !== -1; i = lower.indexOf(q, at)) {
    if (i > at) parts.push(text.slice(at, i))
    parts.push(
      <Box component="mark" key={i} sx={{ background: 'rgba(91, 140, 255, 0.28)', color: 'inherit', borderRadius: '3px' }}>
        {text.slice(i, i + q.length)}
      </Box>,
    )
    at = i + q.length
  }
  parts.push(text.slice(at))
  return <>{parts}</>
}
