import { useEffect, useRef, useState, type MouseEvent } from 'react'
import { Box, Tooltip } from '@mui/material'
import { accent, fg } from './landingTokens'

/**
 * A pilcrow beside a section heading that appears while the heading is
 * hovered. It links to the section, and a click copies the permalink and puts
 * it in the address bar. It takes no width, so centered headings stay
 * centered.
 */
export function SectionAnchor({ id, label }: { id: string; label: string }) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => () => clearTimeout(timer.current), [])

  const copy = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    const url = `${window.location.origin}${window.location.pathname}#${id}`
    window.history.replaceState(window.history.state, '', `#${id}`)
    void navigator.clipboard?.writeText(url)
    setCopied(true)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setCopied(false), 1500)
  }

  return (
    <Box component="span" sx={{ position: 'relative', display: 'inline-block', width: 0 }}>
      <Tooltip title={copied ? 'Link copied' : 'Copy link to this section'} placement="top">
        <Box
          component="a"
          href={`#${id}`}
          onClick={copy}
          aria-label={`Copy link to ${label}`}
          sx={{
            position: 'absolute',
            right: '0.25em',
            bottom: '-0.1em',
            fontSize: '0.78em',
            lineHeight: 1,
            color: copied ? accent.cyan : fg.faint,
            textDecoration: 'none',
            opacity: 0,
            transition: 'opacity 0.2s, color 0.2s',
            'h2:hover &, &:focus-visible': { opacity: 1 },
            '&:hover': { color: accent.cyan },
            '&:focus-visible': { outline: `2px solid ${accent.blue}`, outlineOffset: 2, borderRadius: '4px' },
            '@media (hover: none)': { display: 'none' },
          }}
        >
          ¶
        </Box>
      </Tooltip>
    </Box>
  )
}

export default SectionAnchor
