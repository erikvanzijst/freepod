import { Box, Container, Skeleton, Stack, Typography } from '@mui/material'
import { resolveApiPath } from '../../api/client'
import {
  accentForProduct,
  cardSurface,
  DISPLAY,
  fg,
  MONO,
  SANS,
} from './landingTokens'
import SectionHeading from './SectionHeading'
import Reveal from './Reveal'
import { useLandingProducts, type ProductSummary } from './useLandingProducts'

const gridSx = {
  display: 'grid',
  gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', md: '1fr 1fr 1fr' },
  gap: 2.5,
  mt: { xs: 6, md: 8 },
} as const

/** A single product card, enriched with marketing metadata when available. */
function AppCard({ product }: { product: ProductSummary }) {
  const color = accentForProduct(product.name)
  const blurb = product.description ?? ''

  return (
    <Box
      sx={{
        height: '100%',
        p: 3.5,
        borderRadius: 4,
        ...cardSurface,
        transition: 'transform 0.25s, border-color 0.25s, box-shadow 0.25s',
        '&:hover': {
          transform: 'translateY(-4px)',
          borderColor: `${color}66`,
          boxShadow: `0 18px 50px ${color}22`,
        },
      }}
    >
      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Box
          sx={{
            width: 52,
            height: 52,
            borderRadius: 2.5,
            display: 'grid',
            placeItems: 'center',
            background: `linear-gradient(150deg, ${color}33, ${color}11)`,
            border: `1px solid ${color}44`,
            overflow: 'hidden',
          }}
        >
          {product.iconUrl ? (
            <Box
              component="img"
              src={resolveApiPath(product.iconUrl)}
              alt=""
              sx={{ width: 30, height: 30, objectFit: 'contain' }}
            />
          ) : (
            <Typography sx={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 24, color }}>
              {product.name[0]}
            </Typography>
          )}
        </Box>
        {product.category && (
          <Typography
            sx={{
              fontFamily: MONO,
              fontSize: 11,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              color: fg.faint,
              textAlign: 'right',
            }}
          >
            {product.category}
          </Typography>
        )}
      </Stack>

      <Stack direction="row" alignItems="baseline" spacing={1} sx={{ mt: 3 }}>
        <Typography
          sx={{
            fontFamily: DISPLAY,
            fontWeight: 600,
            fontSize: 26,
            color: fg.primary,
            letterSpacing: '-0.01em',
          }}
        >
          {product.name}
        </Typography>
      </Stack>

      {blurb && (
        <Typography
          sx={{ fontFamily: SANS, fontSize: 15, lineHeight: 1.6, color: fg.muted, mt: 1.5 }}
        >
          {blurb}
        </Typography>
      )}

      {product.replaces && (
        <Box sx={{ mt: 3, pt: 2, borderTop: '1px solid rgba(255,255,255,0.07)' }}>
          <Typography sx={{ fontFamily: SANS, fontSize: 13.5, color: fg.faint }}>
            Replaces{' '}
            <Box component="span" sx={{ color: fg.primary, fontWeight: 600 }}>
              {product.replaces}
            </Box>
          </Typography>
        </Box>
      )}
    </Box>
  )
}

/** Skeleton placeholder shown while products load. */
function AppCardSkeleton() {
  const bar = { bgcolor: 'rgba(255,255,255,0.07)' }
  return (
    <Box sx={{ p: 3.5, borderRadius: 4, ...cardSurface }}>
      <Skeleton variant="rounded" width={52} height={52} sx={bar} />
      <Skeleton variant="text" width="45%" height={34} sx={{ ...bar, mt: 3 }} />
      <Skeleton variant="text" width="95%" sx={bar} />
      <Skeleton variant="text" width="80%" sx={bar} />
    </Box>
  )
}

/** Grid of the real apps Freepod provisions, each framed as a Big-Tech swap. */
export function AppShowcase() {
  const { data, isLoading } = useLandingProducts()

  return (
    <Box component="section" id="apps" sx={{ py: { xs: 9, md: 14 }, scrollMarginTop: 80 }}>
      <Container maxWidth="lg">
        <SectionHeading
          eyebrow="The apps"
          title="Familiar tools, without the surveillance."
          subtitle="Every Freepod app is a best-in-class open-source project, running as your own dedicated instance. Same conveniences you rely on — none of the data harvesting."
        />

        {isLoading || !data ? (
          <Box sx={gridSx}>
            {Array.from({ length: 5 }).map((_, i) => (
              <AppCardSkeleton key={i} />
            ))}
          </Box>
        ) : (
          <Box sx={gridSx}>
            {data.map((product, i) => (
              <Reveal key={product.id} delay={(i % 3) * 90}>
                <AppCard product={product} />
              </Reveal>
            ))}

            {/* "more on the way" tile */}
            <Reveal delay={(data.length % 3) * 90}>
              <Box
                sx={{
                  height: '100%',
                  minHeight: 220,
                  p: 3.5,
                  borderRadius: 4,
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'center',
                  border: '1px dashed rgba(255,255,255,0.14)',
                  background: 'rgba(255,255,255,0.015)',
                }}
              >
                <Typography
                  sx={{ fontFamily: DISPLAY, fontWeight: 500, fontSize: 22, color: fg.primary }}
                >
                  More on the way
                </Typography>
                <Typography
                  sx={{ fontFamily: SANS, fontSize: 14.5, color: fg.muted, mt: 1, lineHeight: 1.6 }}
                >
                  We add carefully vetted open-source apps over time. Have a
                  request? Your vote helps decide what comes next.
                </Typography>
              </Box>
            </Reveal>
          </Box>
        )}
      </Container>
    </Box>
  )
}

export default AppShowcase
