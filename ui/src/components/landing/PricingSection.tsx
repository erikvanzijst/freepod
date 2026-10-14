import { Box, Button, Container, Skeleton, Stack, Typography } from '@mui/material'
import CheckRoundedIcon from '@mui/icons-material/CheckRounded'
import { Link as RouterLink } from 'react-router-dom'
import { resolveApiPath } from '../../api/client'
import { appHref } from '../apppage/appHref'
import { AppIcon } from '../apppage/AppIcon'
import { accent, cardSurface, compareCategories, DISPLAY, fg, line, MONO, primaryButtonSx, SANS } from './landingTokens'
import Reveal from './Reveal'
import { formatEuro, usePricing, type ProductPrice } from './usePricing'

interface PricingSectionProps {
  onSignup: () => void
}

const included = ['A private pod for each app', 'Your own address', 'Hosted in the EU', 'No ads or tracking']

function PriceRow({ product }: { product: ProductPrice }) {
  return (
    <Stack
      component={RouterLink}
      to={appHref(product)}
      direction="row"
      alignItems="center"
      spacing={1.75}
      sx={{
        px: 2.5,
        py: 1.6,
        color: 'inherit',
        textDecoration: 'none',
        borderTop: `1px solid ${line.softer}`,
        '&:first-of-type': { borderTop: 'none' },
        transition: 'background 0.2s',
        '&:hover': { background: 'rgba(255,255,255,0.03)' },
      }}
    >
      <AppIcon name={product.name} src={product.iconUrl ? resolveApiPath(product.iconUrl) : null} size={34} />
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography noWrap sx={{ fontFamily: SANS, fontWeight: 600, fontSize: 15.5 }}>
          {product.name}
        </Typography>
        {product.category && (
          <Typography noWrap sx={{ fontFamily: SANS, fontSize: 13, color: fg.faint }}>
            {product.category}
          </Typography>
        )}
      </Box>
      {product.hasFree && !product.isFallback && (
        <Typography sx={{ display: { xs: 'none', sm: 'block' }, fontFamily: SANS, fontSize: 13.5, color: fg.faint }}>Free plan</Typography>
      )}
      <Typography sx={{ fontFamily: SANS, fontSize: 15, color: fg.muted, whiteSpace: 'nowrap', minWidth: 112, textAlign: 'right' }}>
        {product.isFallback ? (
          product.hasFree ? 'Free' : '—'
        ) : (
          <>
            from <b style={{ color: fg.primary }}>{formatEuro(product.fromCents)}</b>/mo
          </>
        )}
      </Typography>
    </Stack>
  )
}

/** Pricing per app, from the products and plans the API lists. */
export function PricingSection({ onSignup }: PricingSectionProps) {
  const { data, isLoading } = usePricing()
  const prices = [...(data ?? [])].sort((a, b) => compareCategories(a.category ?? '', b.category ?? '') || a.name.localeCompare(b.name))
  const allFree = prices.length > 0 && prices.every((p) => p.hasFree)
  const anyPaid = prices.some((p) => !p.isFallback)

  return (
    <Box component="section" id="pricing" sx={{ py: { xs: 9, md: 13 }, scrollMarginTop: 80 }}>
      <Container
        maxWidth="lg"
        sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '5fr 7fr' }, gap: { xs: 5, md: 10 }, alignItems: 'center' }}
      >
        <Reveal>
          <Typography
            sx={{ fontFamily: MONO, fontSize: 12.5, letterSpacing: '0.22em', textTransform: 'uppercase', color: accent.cyan, mb: 2 }}
          >
            Pricing
          </Typography>
          <Typography
            component="h2"
            sx={{ fontFamily: DISPLAY, fontWeight: 500, fontSize: { xs: 34, md: 46 }, lineHeight: 1.08, letterSpacing: '-0.02em' }}
          >
            Pay only for the apps you run.
          </Typography>
          <Typography sx={{ fontFamily: SANS, fontSize: { xs: 16.5, md: 18 }, lineHeight: 1.6, color: fg.muted, mt: 2.5 }}>
            Each app has its own plans, billed monthly.
            {allFree && ' Every app has a free plan to start with.'}
            {anyPaid && ' Paid plans give you more room as you grow.'}
          </Typography>
          <Stack spacing={1.25} sx={{ mt: 3.5 }}>
            {included.map((item) => (
              <Stack key={item} direction="row" alignItems="center" spacing={1.25}>
                <CheckRoundedIcon sx={{ fontSize: 19, color: '#34D399' }} />
                <Typography sx={{ fontFamily: SANS, fontSize: 15.5, color: fg.primary }}>{item}</Typography>
              </Stack>
            ))}
          </Stack>
          <Button onClick={onSignup} sx={{ ...primaryButtonSx, mt: 4.5 }}>
            Create your account
          </Button>
        </Reveal>

        <Reveal delay={100}>
          <Box sx={{ borderRadius: '12px', overflow: 'hidden', ...cardSurface }}>
            {isLoading &&
              Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} variant="rectangular" height={62} sx={{ bgcolor: 'rgba(255,255,255,0.03)', borderTop: i ? `1px solid ${line.softer}` : 'none' }} />
              ))}
            {prices.map((product) => (
              <PriceRow key={product.id} product={product} />
            ))}
          </Box>
          <Typography sx={{ fontFamily: SANS, fontSize: 13, color: fg.faint, mt: 1.5, textAlign: 'right' }}>
            Lowest paid plan per app, per month.
          </Typography>
        </Reveal>
      </Container>
    </Box>
  )
}

export default PricingSection
