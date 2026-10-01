import { Box, Stack } from '@mui/material'
import { accent, fg, line, MONO, SANS } from '../landingTokens'
import { CopyButton } from '../../CopyButton'
import { highlight, type Lang, type TokenKind } from './highlight'

export interface Snippet {
  label: string
  lang: Lang
  code: string
}

const tokenColor: Record<TokenKind, string> = {
  plain: fg.primary,
  comment: fg.faint,
  string: '#5EEAD4',
  keyword: accent.pink,
  number: '#FBBF24',
  prompt: fg.faint,
  fn: accent.cyan,
}

/** Copyable form of a snippet: shell prompts and trailing comments stripped. */
function copyText(snippet: Snippet): string {
  if (snippet.lang !== 'shell') return snippet.code
  return snippet.code
    .split('\n')
    .filter((l) => l.startsWith('$ '))
    .map((l) => l.slice(2).replace(/\s{2,}#.*$/, ''))
    .join('\n')
}

interface CodeBlockProps {
  snippets: Snippet[]
  /** The selected tab's label; falls back to the first snippet. */
  active?: string
  onSelect?: (label: string) => void
}

/** Dark code panel with optional language tabs and a copy button. */
export function CodeBlock({ snippets, active, onSelect }: CodeBlockProps) {
  const current = snippets.find((s) => s.label === active) ?? snippets[0]

  return (
    <Box
      sx={{
        borderRadius: '12px',
        overflow: 'hidden',
        border: '1px solid rgba(255,255,255,0.09)',
        background: 'rgba(7, 10, 20, 0.85)',
        boxShadow: '0 30px 70px rgba(3, 6, 16, 0.55)',
      }}
    >
      <Stack
        direction="row"
        alignItems="center"
        sx={{ minHeight: 44, pl: 1, pr: 0.5, borderBottom: `1px solid ${line.soft}`, background: 'rgba(255,255,255,0.025)' }}
      >
        <Stack direction="row" role="tablist" sx={{ flex: 1 }}>
          {snippets.map((s) => {
            const selected = s.label === current.label
            return (
              <Box
                key={s.label}
                component="button"
                role="tab"
                aria-selected={selected}
                onClick={() => onSelect?.(s.label)}
                sx={{
                  all: 'unset',
                  cursor: snippets.length > 1 ? 'pointer' : 'default',
                  px: 1.5,
                  py: 1.25,
                  fontFamily: SANS,
                  fontSize: 13.5,
                  fontWeight: 600,
                  color: selected ? fg.primary : fg.faint,
                  boxShadow: selected && snippets.length > 1 ? `inset 0 -2px 0 ${accent.blue}` : 'none',
                  transition: 'color 0.2s',
                  '&:hover': { color: fg.primary },
                  '&:focus-visible': { outline: `2px solid ${accent.blue}`, outlineOffset: -2 },
                }}
              >
                {s.label}
              </Box>
            )
          })}
        </Stack>
        <Box sx={{ color: fg.faint, '& button': { color: 'inherit' } }}>
          <CopyButton value={copyText(current)} label="snippet" />
        </Box>
      </Stack>
      <Box
        component="pre"
        sx={{
          m: 0,
          p: { xs: 2, md: 2.5 },
          fontFamily: MONO,
          fontSize: { xs: 12.5, md: 14 },
          lineHeight: 1.7,
          overflowX: 'auto',
        }}
      >
        <code>
          {highlight(current.code, current.lang).map((tokens, i) => (
            <div key={i}>
              {tokens.every(([text]) => text === '') ? '\u00a0' : null}
              {tokens.map(([text, kind], j) => (
                <span key={j} style={{ color: tokenColor[kind] }}>
                  {text}
                </span>
              ))}
            </div>
          ))}
        </code>
      </Box>
    </Box>
  )
}

export default CodeBlock
