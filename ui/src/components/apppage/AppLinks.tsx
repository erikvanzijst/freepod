import { Box, Stack, Typography } from '@mui/material'
import type { SvgIconComponent } from '@mui/icons-material'
import LanguageRounded from '@mui/icons-material/LanguageRounded'
import MenuBookRounded from '@mui/icons-material/MenuBookRounded'
import CodeRounded from '@mui/icons-material/CodeRounded'
import NewReleasesRounded from '@mui/icons-material/NewReleasesRounded'
import Apple from '@mui/icons-material/Apple'
import Android from '@mui/icons-material/Android'
import OpenInNewRounded from '@mui/icons-material/OpenInNewRounded'
import { fg, line, SANS } from '../landing/landingTokens'
import type { ListingLink } from './listing'

const linkIcons: Record<ListingLink['kind'], SvgIconComponent> = {
  website: LanguageRounded,
  docs: MenuBookRounded,
  source: CodeRounded,
  releases: NewReleasesRounded,
  ios: Apple,
  android: Android,
}

interface AppLinksProps {
  links: ListingLink[]
  /** `list` stacks rows with dividers; `chips` wraps compact pills. */
  layout?: 'list' | 'chips'
}

/** Outbound links to the upstream project: site, docs, source, mobile apps. */
export function AppLinks({ links, layout = 'list' }: AppLinksProps) {
  if (layout === 'chips') {
    return (
      <Stack direction="row" flexWrap="wrap" gap={1}>
        {links.map((link) => {
          const Icon = linkIcons[link.kind]
          return (
            <Box
              key={link.href}
              component="a"
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              sx={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 1,
                px: 1.75,
                py: 0.9,
                borderRadius: 999,
                border: `1px solid ${line.soft}`,
                fontFamily: SANS,
                fontSize: 14,
                color: fg.muted,
                transition: 'color 0.2s, border-color 0.2s, background 0.2s',
                '&:hover': { color: fg.primary, borderColor: 'rgba(148,163,184,0.4)', background: 'rgba(255,255,255,0.04)' },
              }}
            >
              <Icon sx={{ fontSize: 18 }} />
              {link.label}
            </Box>
          )
        })}
      </Stack>
    )
  }

  return (
    <Stack divider={<Box sx={{ borderTop: `1px solid ${line.softer}` }} />}>
      {links.map((link) => {
        const Icon = linkIcons[link.kind]
        return (
          <Stack
            key={link.href}
            component="a"
            href={link.href}
            target="_blank"
            rel="noopener noreferrer"
            direction="row"
            alignItems="center"
            spacing={1.5}
            sx={{
              py: 1.25,
              color: fg.muted,
              transition: 'color 0.2s',
              '&:hover': { color: fg.primary },
              '&:hover .ap-ext': { opacity: 1 },
            }}
          >
            <Icon sx={{ fontSize: 20 }} />
            <Typography sx={{ flex: 1, fontFamily: SANS, fontSize: 15, color: 'inherit' }}>{link.label}</Typography>
            <OpenInNewRounded className="ap-ext" sx={{ fontSize: 16, opacity: 0.4, transition: 'opacity 0.2s' }} />
          </Stack>
        )
      })}
    </Stack>
  )
}

export default AppLinks
