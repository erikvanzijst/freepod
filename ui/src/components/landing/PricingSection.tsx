import { Box, Button, Container, Skeleton, Stack, Typography } from '@mui/material'
import CheckRoundedIcon from '@mui/icons-material/CheckRounded'
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
import { formatEuro, usePricing, type ProductPrice } from './usePricing'

interface PricingSectionProps {
  onSignup: () => void
}

const included = [
  'Your own dedicated instance',
  'Custom domain + automatic HTTPS',
  'No ads, no tracking, ever',
  'Cancel and export anytime',
]

const gridSx = {
  display: 'grid',
  gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', md: '1fr 1fr 1fr' },
  gap: 2.5,
  mt: { xs: 6, md: 8 },
} as const

/** A single product's "starting at" price card. */
function PriceCard({ product, onSignup }: {
  product: ProductPrice
  onSignup: () => void
}) {
  const color = accentForProduct(product.name)

  return (
    <Box
      sx={{
        height: '100%',
        p: 4,
        borderRadius: 4,
        ...cardSurface,
        position: 'relative',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        transition: 'transform 0.25s, border-color 0.25s, box-shadow 0.25s',
        '&:hover': {
          transform: 'translateY(-4px)',
          borderColor: `${color}66`,
          boxShadow: `0 18px 50px ${color}22`,
        },
      }}
    >
      <Box
        sx={{
          position: 'absolute',
          top: -60,
          right: -60,
          width: 160,
          height: 160,
          borderRadius: '50%',
          background: `radial-gradient(circle, ${color}33, transparent 70%)`,
          filter: 'blur(8px)',
        }}
      />

      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Box
          sx={{
            width: 48,
            height: 48,
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
              sx={{ width: 28, height: 28, objectFit: 'contain' }}
            />
          ) : (
            <Typography sx={{ fontFamily: DISPLAY, fontWeight: 600, color }}>
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

      <Typography
        sx={{
          fontFamily: DISPLAY,
          fontWeight: 600,
          fontSize: 26,
          color: fg.primary,
          mt: 3,
        }}
      >
        {product.name}
      </Typography>

      <Typography
        sx={{
          fontFamily: MONO,
          fontSize: 11,
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
          color,
          mt: 2.5,
        }}
      >
        Starting at
      </Typography>
      <Stack direction="row" alignItems="baseline" spacing={1} sx={{ mt: 0.5 }}>
        <Typography
          sx={{
            fontFamily: DISPLAY,
            fontWeight: 600,
            fontSize: 52,
            lineHeight: 1,
            color: fg.primary,
          }}
        >
          {formatEuro(product.fromCents)}
        </Typography>
        <Typography sx={{ fontFamily: SANS, fontSize: 15, color: fg.muted }}>
          / month
        </Typography>
      </Stack>

      {product.replaces && (
        <Typography
          sx={{ fontFamily: SANS, fontSize: 14, color: fg.muted, mt: 1.5 }}
        >
          An alternative to{' '}
          <Box component="span" sx={{ color: fg.primary, fontWeight: 600 }}>
            {product.replaces}
          </Box>
        </Typography>
      )}

      <Box sx={{ flex: 1 }} />

      <Button
        fullWidth
        onClick={onSignup}
        sx={{
          mt: 3.5,
          borderRadius: 999,
          py: 1.25,
          fontWeight: 600,
          color: fg.primary,
          border: '1px solid rgba(255,255,255,0.18)',
          background: 'rgba(255,255,255,0.04)',
          '&:hover': {
            background: 'rgba(255,255,255,0.09)',
            borderColor: `${color}aa`,
          },
        }}
      >
        Get started
      </Button>
    </Box>
  )
}

/** Skeleton placeholder shown while pricing loads. */
function PriceCardSkeleton() {
  const bar = { bgcolor: 'rgba(255,255,255,0.07)' }
  return (
    <Box sx={{ p: 4, borderRadius: 4, ...cardSurface }}>
      <Skeleton variant="rounded" width={48} height={48} sx={bar} />
      <Skeleton variant="text" width="55%" height={34} sx={{ ...bar, mt: 3 }} />
      <Skeleton variant="text" width="40%" height={56} sx={{ ...bar, mt: 2 }} />
      <Skeleton variant="rounded" height={42} sx={{ ...bar, mt: 4, borderRadius: 999 }} />
    </Box>
  )
}

/** Pricing section, driven live by the products + plans APIs. */
export function PricingSection({ onSignup }: PricingSectionProps) {
  const { data, isLoading } = usePricing()

  return (
    <Box component="section" id="pricing" sx={{ py: { xs: 9, md: 14 }, scrollMarginTop: 80 }}>
      <Container maxWidth="lg">
        <SectionHeading
          eyebrow="Pricing"
          title="Honest pricing. You’re the customer, not the product."
          subtitle="Pay only for the apps you use. Every plan includes a private instance, your own domain and zero advertising — because you fund Freepod, not advertisers."
        />

        {isLoading || !data ? (
          <Box sx={gridSx}>
            {Array.from({ length: 5 }).map((_, i) => (
              <PriceCardSkeleton key={i} />
            ))}
          </Box>
        ) : (
          <Box sx={gridSx}>
            {data.map((product, i) => (
              <Reveal key={product.id} delay={(i % 3) * 90}>
                <PriceCard product={product} onSignup={onSignup} />
              </Reveal>
            ))}
          </Box>
        )}

        {/* Included-in-every-plan strip */}
        <Reveal delay={120}>
          <Stack
            direction="row"
            flexWrap="wrap"
            justifyContent="center"
            spacing={3}
            useFlexGap
            sx={{ mt: 6 }}
          >
            {included.map((item) => (
              <Stack key={item} direction="row" alignItems="center" spacing={1}>
                <CheckRoundedIcon sx={{ fontSize: 18, color: '#34d399' }} />
                <Typography sx={{ fontFamily: SANS, fontSize: 14.5, color: fg.muted }}>
                  {item}
                </Typography>
              </Stack>
            ))}
          </Stack>
        </Reveal>

        <Typography
          sx={{
            fontFamily: SANS,
            fontSize: 12.5,
            color: fg.faint,
            textAlign: 'center',
            mt: 4,
          }}
        >
          Starting prices shown per app, billed monthly. Choose your plan and
          storage when you sign up.
        </Typography>
      </Container>
    </Box>
  )
}

export default PricingSection
