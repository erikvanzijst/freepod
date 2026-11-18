import type { ReactNode } from 'react'
import { Box, Typography } from '@mui/material'
import { accent, DISPLAY, fg, MONO, SANS } from './landingTokens'
import SectionAnchor from './SectionAnchor'

interface SectionHeadingProps {
  eyebrow: string
  title: ReactNode
  subtitle?: string
  align?: 'left' | 'center'
  /** The section's id: shows a permalink beside the title while it is hovered. */
  anchor?: string
}

/** Consistent eyebrow + serif title + optional subtitle block for sections. */
export function SectionHeading({
  eyebrow,
  title,
  subtitle,
  align = 'center',
  anchor,
}: SectionHeadingProps) {
  return (
    <Box
      sx={{
        textAlign: align,
        mx: align === 'center' ? 'auto' : 0,
        maxWidth: align === 'center' ? 720 : 'none',
      }}
    >
      <Typography
        sx={{
          fontFamily: MONO,
          fontSize: 12.5,
          letterSpacing: '0.22em',
          textTransform: 'uppercase',
          color: accent.cyan,
          mb: 2,
        }}
      >
        {eyebrow}
      </Typography>
      <Typography
        component="h2"
        sx={{
          fontFamily: DISPLAY,
          fontWeight: 500,
          color: fg.primary,
          fontSize: { xs: 32, md: 46 },
          lineHeight: 1.08,
          letterSpacing: '-0.02em',
        }}
      >
        {anchor && <SectionAnchor id={anchor} label={eyebrow} />}
        {title}
      </Typography>
      {subtitle && (
        <Typography
          sx={{
            fontFamily: SANS,
            color: fg.muted,
            fontSize: { xs: 16, md: 18 },
            lineHeight: 1.6,
            mt: 2.5,
            maxWidth: 640,
            mx: align === 'center' ? 'auto' : 0,
          }}
        >
          {subtitle}
        </Typography>
      )}
    </Box>
  )
}

export default SectionHeading
