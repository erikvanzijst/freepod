import { Box, Container, Stack, Typography } from '@mui/material'
import ArrowForwardRounded from '@mui/icons-material/ArrowForwardRounded'
import { Link as RouterLink } from 'react-router-dom'
import { resolveApiPath } from '../../api/client'
import { accentForProduct, cardSurface, DISPLAY, fg, MONO, SANS } from '../landing/landingTokens'
import { useLandingProducts } from '../landing/useLandingProducts'
import { appHref } from './appHref'

interface RelatedAppsProps {
  currentName: string
  category?: string
  title?: string
}

/**
 * "More apps" rail at the foot of the page, same-category apps first, so a
 * visitor who deep-linked in has somewhere to go next.
 */
export function RelatedApps({ currentName, category, title = 'More apps on Freepod' }: RelatedAppsProps) {
  const { data = [] } = useLandingProducts()
  const others = data
    .filter((p) => p.name !== currentName)
    .sort((a, b) => Number(b.category === category) - Number(a.category === category))

  return (
    <Box component="section" sx={{ py: { xs: 7, md: 10 } }}>
      <Container maxWidth="lg">
        <Stack direction="row" alignItems="baseline" justifyContent="space-between" sx={{ mb: 3.5 }}>
          <Typography sx={{ fontFamily: DISPLAY, fontWeight: 500, fontSize: { xs: 26, md: 32 }, letterSpacing: '-0.01em' }}>
            {title}
          </Typography>
          <Box
            component={RouterLink}
            to="/apps"
            sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, fontSize: 15, color: fg.muted, '&:hover': { color: fg.primary } }}
          >
            All apps <ArrowForwardRounded sx={{ fontSize: 18 }} />
          </Box>
        </Stack>
        <Box
          sx={{
            display: 'grid',
            gridAutoFlow: 'column',
            gridAutoColumns: { xs: '78%', sm: '44%', md: 'calc((100% - 60px) / 4)' },
            gap: 2.5,
            overflowX: 'auto',
            scrollSnapType: 'x mandatory',
            pb: 1,
            scrollbarWidth: 'none',
            '&::-webkit-scrollbar': { display: 'none' },
          }}
        >
          {others.map((p) => {
            const color = accentForProduct(p.name)
            return (
              <Box
                key={p.id}
                component={RouterLink}
                to={appHref(p)}
                sx={{
                  scrollSnapAlign: 'start',
                  p: 2.75,
                  borderRadius: '16px',
                  ...cardSurface,
                  transition: 'transform 0.25s, border-color 0.25s',
                  '&:hover': { transform: 'translateY(-3px)', borderColor: `${color}66` },
                }}
              >
                <Stack direction="row" spacing={1.75} alignItems="center">
                  <Box
                    sx={{
                      width: 44,
                      height: 44,
                      borderRadius: '10px',
                      display: 'grid',
                      placeItems: 'center',
                      background: `linear-gradient(150deg, ${color}33, ${color}11)`,
                      border: `1px solid ${color}44`,
                    }}
                  >
                    {p.iconUrl && (
                      <Box component="img" src={resolveApiPath(p.iconUrl)} alt="" sx={{ width: 26, height: 26 }} />
                    )}
                  </Box>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography noWrap sx={{ fontFamily: SANS, fontWeight: 600, fontSize: 16, color: fg.primary }}>
                      {p.name}
                    </Typography>
                    <Typography noWrap sx={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: '0.12em', textTransform: 'uppercase', color: fg.faint }}>
                      {p.category ?? 'App'}
                    </Typography>
                  </Box>
                </Stack>
                {p.replaces && (
                  <Typography noWrap sx={{ mt: 2, fontSize: 13.5, color: fg.faint }}>
                    An alternative to <Box component="span" sx={{ color: fg.muted }}>{p.replaces}</Box>
                  </Typography>
                )}
              </Box>
            )
          })}
        </Box>
      </Container>
    </Box>
  )
}

export default RelatedApps
