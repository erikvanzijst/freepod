import type { Ref } from 'react'
import { Box, type SxProps, type Theme } from '@mui/material'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { fg, MONO, SANS } from '../landing/landingTokens'

const markdownSx = {
  fontFamily: SANS,
  color: fg.muted,
  fontSize: 15.5,
  lineHeight: 1.7,
  '& p': { m: 0, mb: 2 },
  '& h3': { fontFamily: SANS, fontSize: 13, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: fg.primary, mt: 2.5, mb: 1 },
  '& ul': { m: 0, pl: 2.5 },
  '& li': { mb: 0.5 },
  '& code': { fontFamily: MONO, fontSize: 13, px: 0.5, borderRadius: '4px', background: 'rgba(255,255,255,0.06)' },
} as const

interface MarkdownProps {
  children: string
  sx?: SxProps<Theme>
  boxRef?: Ref<HTMLDivElement>
}

/** Catalog Markdown in the page's typography. Raw HTML is dropped, never rendered. */
export function Markdown({ children, sx, boxRef }: MarkdownProps) {
  return (
    <Box ref={boxRef} sx={[markdownSx, ...(Array.isArray(sx) ? sx : [sx])]}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
        {children}
      </ReactMarkdown>
    </Box>
  )
}

export default Markdown
