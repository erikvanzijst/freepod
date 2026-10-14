import { Fragment, useState, type ReactNode } from 'react'
import { Box, Container, Stack, Typography } from '@mui/material'
import { cardSurface, DISPLAY, fg, line, MONO, SANS } from '../landing/landingTokens'
import { formatEuro } from '../landing/usePricing'
import { AppIcon } from './AppIcon'
import { AppFacts } from './AppFacts'
import { AppLinks } from './AppLinks'
import { CatalogBar } from './CatalogBar'
import { FeatureList } from './FeatureList'
import { InstallButton } from './InstallButton'
import { PlanPicker } from './PlanPicker'
import { RelatedApps } from './RelatedApps'
import { ReleaseNotes } from './ReleaseNotes'
import { ScreenshotLightbox } from './ScreenshotLightbox'
import { ScreenshotStrip } from './ScreenshotStrip'
import { Markdown } from './Markdown'
import { planPrice, planSummary } from './listingFormat'
import { defaultPlanIndex, fromPriceCents, type AppListing } from './listing'
import { findPlan } from '../useInstallRequest'

const divider = <Box sx={{ borderTop: `1px solid ${line.soft}`, my: { xs: 4, md: 5 } }} />

const h2Sx = { fontFamily: DISPLAY, fontWeight: 500, fontSize: { xs: 24, md: 28 }, letterSpacing: '-0.01em', mb: 2.5 } as const

/** Headline and small print for the price, from whichever plans exist. */
function priceSummary(listing: AppListing): { headline: string; sub: string } | null {
  if (listing.plans.length === 0) return null
  const hasFree = listing.plans.some((p) => p.priceCents === 0)
  const from = fromPriceCents(listing)
  if (hasFree && from) return { headline: 'Free', sub: `or from ${formatEuro(from)}/mo` }
  if (from) return { headline: `From ${formatEuro(from)} / month`, sub: 'Cancel anytime' }
  return { headline: 'Free', sub: '' }
}

/** Quick facts under the header: a ruled row on desktop, a swipeable rail on phones. */
function StatBar({ listing }: { listing: AppListing }) {
  const platforms = [
    listing.links.some((l) => l.kind === 'ios') && 'iOS',
    listing.links.some((l) => l.kind === 'android') && 'Android',
  ].filter(Boolean)
  const from = fromPriceCents(listing)
  const stats = [
    listing.version && { value: listing.version, label: 'Version', mono: true },
    listing.license && { value: listing.license, label: 'License' },
    { value: 'EU', label: 'Hosted in' },
    platforms.length > 0 && { value: platforms.join(' · '), label: 'Mobile apps' },
    listing.plans.length > 0 && (from ? { value: `${formatEuro(from)}/mo`, label: 'Plans from' } : { value: 'Free', label: 'Price' }),
  ].filter((s): s is { value: string; label: string; mono?: boolean } => Boolean(s))

  return (
    <Box
      sx={{
        display: 'grid',
        gridAutoFlow: 'column',
        gridAutoColumns: { xs: 'max-content', md: '1fr' },
        overflowX: 'auto',
        scrollbarWidth: 'none',
        '&::-webkit-scrollbar': { display: 'none' },
        borderTop: { md: `1px solid ${line.soft}` },
        borderBottom: { md: `1px solid ${line.soft}` },
        '& > *:not(:last-child)': { borderRight: `1px solid ${line.softer}` },
      }}
    >
      {stats.map((s) => (
        <Box key={s.label} sx={{ py: { xs: 0.5, md: 2.25 }, px: { xs: 2.25, md: 2 }, textAlign: 'center', '&:first-of-type': { pl: { xs: 0, md: 2 } } }}>
          <Typography sx={{ fontFamily: s.mono ? MONO : SANS, fontWeight: 600, fontSize: { xs: 15, md: 17 } }}>{s.value}</Typography>
          <Typography sx={{ fontSize: 12, color: fg.faint, mt: 0.25 }}>{s.label}</Typography>
        </Box>
      ))}
    </Box>
  )
}

/**
 * An app's store listing: identity header, stat bar and screenshot strip on
 * top; features, description, release notes and details beside a sticky plan
 * card beneath. On phones the header shrinks to a title row so screenshots
 * show at once, and the install action moves to a bar pinned to the bottom.
 * Every section is optional, so a sparsely described app still renders cleanly.
 * `initialPlan` names a plan to preselect instead of the default, as from a
 * `?plan=<name>` deep link; an unknown name falls back to the default.
 */
export function AppListingView({
  listing,
  initialPlan,
  onInstall,
}: {
  listing: AppListing
  initialPlan?: string
  onInstall: (plan?: string) => void
}) {
  const [shot, setShot] = useState<number | null>(null)
  const [plan, setPlan] = useState(() => {
    const requested = findPlan(listing.plans, initialPlan)
    return requested ? listing.plans.indexOf(requested) : defaultPlanIndex(listing)
  })
  const selected = listing.plans[plan]
  const price = priceSummary(listing)
  const hasFreePlan = listing.plans.some((p) => p.priceCents === 0)
  const meta = [listing.category, listing.replaces.length > 0 && `An alternative to ${listing.replaces.join(' · ')}`].filter(Boolean).join(' · ')

  const sections: ReactNode[] = [
    listing.features.length > 0 && <FeatureList features={listing.features} />,
    listing.description && (
      <>
        <Typography component="h2" sx={h2Sx}>About {listing.name}</Typography>
        <Markdown sx={{ fontSize: 16.5, lineHeight: 1.75 }}>{listing.description}</Markdown>
      </>
    ),
    listing.releases.length > 0 && <ReleaseNotes releases={listing.releases} />,
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: { xs: 5, sm: 6 } }}>
      <Box>
        <Typography component="h2" sx={{ ...h2Sx, fontSize: 22 }}>Details</Typography>
        <AppFacts listing={listing} />
      </Box>
      {listing.links.length > 0 && (
        <Box>
          <Typography component="h2" sx={{ ...h2Sx, fontSize: 22 }}>From the {listing.name} project</Typography>
          <AppLinks links={listing.links} />
        </Box>
      )}
    </Box>,
  ].filter(Boolean)

  return (
    <>
      <CatalogBar trail={[listing.category, listing.name].filter(Boolean)} />

      <Container maxWidth="lg" sx={{ pt: { xs: 3, md: 7 }, pb: { xs: 12, md: 0 } }}>
        {/* Header */}
        <Stack direction="row" spacing={{ xs: 2, md: 4 }} alignItems="center">
          <Box sx={{ display: { xs: 'none', md: 'block' } }}>
            <AppIcon name={listing.name} src={listing.iconUrl} size={120} />
          </Box>
          <Box sx={{ display: { xs: 'block', md: 'none' } }}>
            <AppIcon name={listing.name} src={listing.iconUrl} size={60} />
          </Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography component="h1" sx={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: { xs: 32, md: 60 }, lineHeight: 1, letterSpacing: '-0.025em' }}>
              {listing.name}
            </Typography>
            {listing.tagline && (
              <Typography sx={{ display: { xs: 'none', md: 'block' }, mt: 1.5, fontSize: 19, color: fg.muted, maxWidth: 620 }}>
                {listing.tagline}
              </Typography>
            )}
            {meta && (
              <Typography sx={{ mt: { xs: 0.75, md: 1.5 }, fontSize: { xs: 14, md: 15 }, color: fg.faint }}>{meta}</Typography>
            )}
          </Box>
          <Stack alignItems="flex-end" spacing={1} sx={{ display: { xs: 'none', md: 'flex' } }}>
            <InstallButton onClick={() => onInstall(selected?.name)}>Install {listing.name}</InstallButton>
            <Typography sx={{ fontSize: 13, color: fg.faint }}>
              {hasFreePlan ? 'Free plan available · cancel anytime' : 'Cancel anytime'}
            </Typography>
          </Stack>
        </Stack>

        {/* Phones: screenshots before the stat rail. */}
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: { xs: 3, md: 5 }, mt: { xs: 3, md: 5 } }}>
          <Box sx={{ order: { xs: 2, md: 1 } }}>
            <StatBar listing={listing} />
          </Box>
          {listing.screenshots.length > 0 && (
            <Box sx={{ order: { xs: 1, md: 2 } }}>
              <ScreenshotStrip shots={listing.screenshots} onOpen={setShot} />
            </Box>
          )}
        </Box>

        {/* Body */}
        <Box
          sx={{
            mt: { xs: 5, md: 8 },
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: '1fr 360px' },
            gap: { xs: 0, md: 9 },
            alignItems: 'start',
          }}
        >
          <Box sx={{ minWidth: 0 }}>
            {listing.tagline && (
              <Typography sx={{ display: { md: 'none' }, fontFamily: DISPLAY, fontSize: 24, lineHeight: 1.3, mb: 4 }}>
                {listing.tagline}
              </Typography>
            )}
            {sections.map((section, i) => (
              <Fragment key={i}>
                {i > 0 && divider}
                {section}
              </Fragment>
            ))}
          </Box>

          {/* Sticky plan card */}
          <Box
            sx={{
              display: { xs: 'none', md: 'block' },
              position: 'sticky',
              top: 96,
              p: 3.5,
              borderRadius: '20px',
              ...cardSurface,
              boxShadow: '0 30px 80px rgba(0,0,0,0.45)',
            }}
          >
            {selected && (
              <>
                <Stack direction="row" alignItems="baseline" spacing={0.75} sx={{ mb: 2.5 }}>
                  <Typography sx={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 36, lineHeight: 1 }}>{planPrice(selected)}</Typography>
                  {selected.priceCents > 0 && <Typography sx={{ color: fg.muted }}>/ month</Typography>}
                </Stack>
                {listing.plans.length > 1 ? (
                  <PlanPicker plans={listing.plans} selected={plan} onSelect={setPlan} />
                ) : (
                  <Typography sx={{ mt: -1.5, fontSize: 14.5, color: fg.muted }}>{planSummary(selected)}</Typography>
                )}
              </>
            )}
            <InstallButton fullWidth onClick={() => onInstall(selected?.name)} sx={{ mt: selected ? 2.5 : 0 }}>
              {selected && listing.plans.length > 1 ? `Install with ${selected.name}` : `Install ${listing.name}`}
            </InstallButton>
            <Typography sx={{ mt: 1.5, textAlign: 'center', fontSize: 13, color: fg.faint }}>
              Automatic updates · cancel anytime
            </Typography>
          </Box>
        </Box>
      </Container>

      <RelatedApps currentName={listing.name} category={listing.category} title={`More like ${listing.name}`} />

      {/* Phones: pinned install bar */}
      <Stack
        direction="row"
        alignItems="center"
        sx={{
          display: { xs: 'flex', md: 'none' },
          position: 'fixed',
          left: 0,
          right: 0,
          bottom: 0,
          zIndex: 30,
          px: 2.5,
          py: 1.5,
          gap: 2,
          background: 'rgba(7,10,20,0.92)',
          backdropFilter: 'blur(14px)',
          borderTop: `1px solid ${line.soft}`,
        }}
      >
        <Box sx={{ flex: 1 }}>
          {price && (
            <>
              <Typography sx={{ fontWeight: 600, fontSize: 16 }}>{price.headline}</Typography>
              {price.sub && <Typography sx={{ fontSize: 13, color: fg.faint }}>{price.sub}</Typography>}
            </>
          )}
        </Box>
        <InstallButton onClick={() => onInstall(selected?.name)} sx={{ px: 3, py: 1.1, fontSize: 15.5 }}>Install</InstallButton>
      </Stack>

      <ScreenshotLightbox shots={listing.screenshots} index={shot} onIndexChange={setShot} onClose={() => setShot(null)} />
    </>
  )
}

export default AppListingView
