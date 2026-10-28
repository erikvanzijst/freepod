import { Box, Stack, Typography } from '@mui/material'
import MenuBookRounded from '@mui/icons-material/MenuBookRounded'
import ArrowForwardRounded from '@mui/icons-material/ArrowForwardRounded'
import { fg, line, SANS } from '../landing/landingTokens'
import { appDocsHref } from './appDocs'

/** A ruled row linking to the app's page in the Freepod docs; renders nothing for an app without one. */
export function AppDocsLink({ slug, name }: { slug: string; name: string }) {
  const href = appDocsHref(slug)
  if (!href) return null
  return (
    <Stack
      component="a"
      href={href}
      direction="row"
      alignItems="center"
      spacing={1.5}
      sx={{
        mt: 3,
        pt: 2.5,
        borderTop: `1px solid ${line.soft}`,
        color: fg.muted,
        textDecoration: 'none',
        '&:hover': { color: fg.primary },
        '&:hover .docs-arrow': { transform: 'translateX(3px)' },
      }}
    >
      <MenuBookRounded sx={{ fontSize: 22 }} />
      <Box sx={{ flex: 1 }}>
        <Typography sx={{ fontFamily: SANS, fontWeight: 600, fontSize: 15, color: fg.primary }}>{name} docs</Typography>
        <Typography sx={{ fontFamily: SANS, fontSize: 13, color: fg.faint }}>Sign-in, settings and more</Typography>
      </Box>
      <ArrowForwardRounded className="docs-arrow" sx={{ fontSize: 18, transition: 'transform 0.2s' }} />
    </Stack>
  )
}

export default AppDocsLink
