import { createElement } from 'react'
import { Box, Container, Skeleton, Stack, Typography } from '@mui/material'
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded'
import { Link as RouterLink } from 'react-router-dom'
import { resolveApiPath } from '../../api/client'
import { AppIcon } from '../apppage/AppIcon'
import { accent, cardSurface, categoryIcon, DISPLAY, fg, line, MONO, SANS } from './landingTokens'
import SectionHeading from './SectionHeading'
import Reveal from './Reveal'
import { useLandingProducts } from './useLandingProducts'
import { groupByNeed, orList, type Need } from './needs'

const SHOWN = 6

/** One need: what it replaces, in words a visitor knows, with the apps that do it in small print. */
function NeedCard({ need }: { need: Need }) {
  return (
    <Box
      component={RouterLink}
      to={`/apps?category=${encodeURIComponent(need.category)}`}
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        p: 3,
        borderRadius: '12px',
        color: 'inherit',
        textDecoration: 'none',
        ...cardSurface,
        transition: 'transform 0.25s, border-color 0.25s',
        '&:hover': { transform: 'translateY(-3px)', borderColor: 'rgba(255,255,255,0.2)' },
      }}
    >
      <Box
        sx={{
          width: 44,
          height: 44,
          borderRadius: '10px',
          display: 'grid',
          placeItems: 'center',
          background: `linear-gradient(150deg, ${accent.blue}33, ${accent.magenta}1f)`,
          border: `1px solid ${accent.blue}40`,
        }}
      >
        {createElement(categoryIcon(need.category), { sx: { fontSize: 23, color: fg.primary } })}
      </Box>
      <Typography sx={{ fontFamily: DISPLAY, fontWeight: 500, fontSize: 24, mt: 2.25, color: fg.primary }}>{need.category}</Typography>
      {need.alternatives.length > 0 && (
        <Typography sx={{ fontFamily: SANS, fontSize: 15, color: accent.cyan, mt: 0.5 }}>
          An alternative to {orList(need.alternatives.slice(0, 3))}
        </Typography>
      )}
      {need.blurb && (
        <Typography sx={{ fontFamily: SANS, fontSize: 15, lineHeight: 1.55, color: fg.muted, mt: 1.5 }}>{need.blurb}</Typography>
      )}
      <Box sx={{ flex: 1 }} />
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 2.5, pt: 1.75, borderTop: `1px solid ${line.softer}` }}>
        <Stack direction="row" spacing={-0.75}>
          {need.apps.map((app) => (
            <AppIcon key={app.id} name={app.name} src={app.iconUrl ? resolveApiPath(app.iconUrl) : null} size={22} />
          ))}
        </Stack>
        <Typography noWrap sx={{ fontFamily: SANS, fontSize: 13.5, color: fg.faint }}>
          With {orList(need.apps.map((a) => a.name))}
        </Typography>
      </Stack>
    </Box>
  )
}

/** What people keep in the cloud, each with the Freepod apps that do it, linking into the catalog. */
export function AppShowcase() {
  const { data: products, isLoading } = useLandingProducts()
  const needs = groupByNeed(products ?? [])

  return (
    <Box component="section" id="apps" sx={{ py: { xs: 9, md: 13 }, scrollMarginTop: 80 }}>
      <Container maxWidth="lg">
        <SectionHeading
          eyebrow="What you can run"
          title="For everything you keep in the cloud."
          subtitle="Freepod offers a collection of high quality, curated open source applications. Each a private alternative to a service you already know."
        />

        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', md: 'repeat(3, 1fr)' },
            gap: 2,
            mt: { xs: 6, md: 7 },
          }}
        >
          {isLoading &&
            Array.from({ length: SHOWN }).map((_, i) => (
              <Skeleton key={i} variant="rounded" height={240} sx={{ borderRadius: '12px', bgcolor: 'rgba(255,255,255,0.05)' }} />
            ))}
          {needs.slice(0, SHOWN).map((need, i) => (
            <Reveal key={need.category} delay={(i % 3) * 80}>
              <NeedCard need={need} />
            </Reveal>
          ))}
        </Box>

        <Box sx={{ textAlign: 'center', mt: 5 }}>
          <Box
            component={RouterLink}
            to="/apps"
            sx={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 0.75,
              fontFamily: MONO,
              fontSize: 13.5,
              letterSpacing: '0.06em',
              color: fg.muted,
              textDecoration: 'none',
              '&:hover': { color: fg.primary },
            }}
          >
            See all the apps <ArrowForwardRoundedIcon sx={{ fontSize: 18 }} />
          </Box>
        </Box>
      </Container>
    </Box>
  )
}

export default AppShowcase
