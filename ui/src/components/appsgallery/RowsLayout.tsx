import { Box, Collapse, Container, Stack, Typography } from '@mui/material'
import ExpandMoreRounded from '@mui/icons-material/ExpandMoreRounded'
import { useSearchParams } from 'react-router-dom'
import { fg, line } from '../landing/landingTokens'
import AppIcon from '../apppage/AppIcon'
import { AlternativeTo, AppPreviewBody, CategoryChips, GalleryIntro, NoResults, PriceTag, RunningBadge, SearchField } from './GalleryParts'
import type { GalleryApp, useGallery } from './useGallery'

type Gallery = ReturnType<typeof useGallery>

/** The catalog as a list of rows; a row expands in place to show screenshots, features and plans. */
export function RowsLayout({ g, onInstall }: { g: Gallery; onInstall: (app: GalleryApp, planId?: number) => void }) {
  const [params, setParams] = useSearchParams()
  const open = params.get('open')
  const toggle = (slug: string) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        if (open === slug) next.delete('open')
        else next.set('open', slug)
        return next
      },
      { replace: true },
    )

  return (
    <Container maxWidth="lg" sx={{ pt: { xs: 5, md: 9 }, pb: 14 }}>
      <GalleryIntro />
      <Box sx={{ mt: 5, mb: 2.5, maxWidth: 640 }}>
        <SearchField value={g.q} onChange={(v) => g.setFilter('q', v)} fullWidth />
      </Box>
      <CategoryChips categories={g.categories} total={g.apps.length} active={g.category} onSelect={(c) => g.setFilter('category', c)} />

      <Box sx={{ mt: 4, borderTop: `1px solid ${line.soft}` }}>
        {g.results.map((app) => {
          const expanded = open === app.href
          return (
            <Box key={app.id} sx={{ borderBottom: `1px solid ${line.soft}` }}>
              <Stack
                component="button"
                direction="row"
                alignItems="center"
                spacing={{ xs: 1.75, sm: 2.5 }}
                onClick={() => toggle(app.href)}
                aria-expanded={expanded}
                sx={{
                  width: 1,
                  py: 2.25,
                  px: 1,
                  background: 'none',
                  border: 0,
                  cursor: 'pointer',
                  color: 'inherit',
                  textAlign: 'left',
                  font: 'inherit',
                  '&:hover .chev': { color: fg.primary },
                }}
              >
                <AppIcon name={app.name} src={app.iconUrl ?? null} size={48} />
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Stack direction="row" alignItems="center" spacing={1.25}>
                    <Typography sx={{ fontWeight: 600, fontSize: 17 }}>{app.name}</Typography>
                    <Typography sx={{ fontSize: 13, color: fg.faint, display: { xs: 'none', sm: 'block' } }}>{app.category}</Typography>
                    <RunningBadge count={app.running} />
                  </Stack>
                  <Typography sx={{ fontSize: 14.5, color: fg.muted, lineHeight: 1.45 }}>{app.tagline}</Typography>
                  <Box sx={{ display: { sm: 'none' }, mt: 0.5 }}>
                    <PriceTag app={app} />
                  </Box>
                </Box>
                <Box sx={{ display: { xs: 'none', sm: 'block' } }}>
                  <PriceTag app={app} />
                </Box>
                <ExpandMoreRounded
                  className="chev"
                  sx={{ color: fg.faint, transition: 'transform 0.2s', transform: expanded ? 'rotate(180deg)' : 'none' }}
                />
              </Stack>
              <Collapse in={expanded} unmountOnExit>
                <Box sx={{ pl: { xs: 1, sm: 10 }, pr: 1, pb: 4, pt: 0.5 }}>
                  <Box sx={{ mb: 2.5 }}>
                    <AlternativeTo app={app} />
                  </Box>
                  <AppPreviewBody app={app} onInstall={(planId) => onInstall(app, planId)} />
                </Box>
              </Collapse>
            </Box>
          )
        })}
      </Box>
      {!g.loading && g.results.length === 0 && (
        <NoResults q={g.q || g.category} onReset={() => { g.setFilter('q', ''); g.setFilter('category', '') }} />
      )}
    </Container>
  )
}
