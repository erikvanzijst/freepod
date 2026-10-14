import { Box, Stack, Typography } from '@mui/material'
import { cardSurface, fg, line, MONO, SANS } from '../landingTokens'
import Reveal from '../Reveal'
import { euro, floorCost, rates, type ResourceId } from './devPricing'
import { EstimateSliders, EstimateTotal, PresetChips, PricingFrame, RateRows } from './estimator'
import { useEstimate } from './useEstimate'

const floor = (id: ResourceId) => rates.find((r) => r.id === id)?.floor ?? 0

function Label({ title, hint }: { title: string; hint: string }) {
  return (
    <Stack direction="row" alignItems="baseline" spacing={1.5} sx={{ mb: 1.75, minHeight: 24 }}>
      <Typography sx={{ fontFamily: MONO, fontSize: 12.5, letterSpacing: '0.18em', textTransform: 'uppercase', color: fg.primary }}>
        {title}
      </Typography>
      <Typography sx={{ fontFamily: SANS, fontSize: 13.5, color: fg.faint }}>{hint}</Typography>
    </Stack>
  )
}

/**
 * Pricing for the developer landing page: unit rates as a flat reference list
 * beside a cost calculator, the one raised card.
 */
export function DevPricing() {
  const estimate = useEstimate()

  return (
    <PricingFrame>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '5fr 7fr' }, gap: { xs: 5, md: 6 }, alignItems: 'stretch' }}>
        <Reveal sx={{ display: 'flex', flexDirection: 'column' }}>
          <Label title="Rates" hint="per unit, billed hourly" />
          <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', borderBottom: `1px solid ${line.soft}`, '& > :first-of-type': { borderTopColor: line.soft } }}>
            <RateRows px={0.5} />
          </Box>
          <Typography sx={{ fontFamily: SANS, fontSize: 14, lineHeight: 1.6, color: fg.muted, mt: 2 }}>
            <Box component="span" aria-hidden sx={{ color: fg.faint, mr: 0.5 }}>
              *
            </Box>
            You pay for what your app actually uses, measured every hour, not for a whole vCPU. An idle app
            is billed at its floor of {floor('cpu')}&nbsp;vCPU and {floor('memory') * 1024}&nbsp;MiB, about {euro(floorCost)} a month.
          </Typography>
        </Reveal>

        <Reveal delay={100} sx={{ display: 'flex', flexDirection: 'column' }}>
          <Label title="Calculator" hint="estimate what an app costs" />
          <Box
            sx={{
              flex: 1,
              borderRadius: '12px',
              overflow: 'hidden',
              ...cardSurface,
              boxShadow: '0 24px 60px rgba(3,6,16,0.45)',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <Box sx={{ px: { xs: 2.5, md: 3.5 }, pt: 3 }}>
              <PresetChips estimate={estimate} />
            </Box>
            <Box sx={{ px: { xs: 2.5, md: 3.5 }, py: 3, flex: 1 }}>
              <EstimateSliders estimate={estimate} />
            </Box>
            <EstimateTotal estimate={estimate} label="Estimated per month" />
          </Box>
        </Reveal>
      </Box>
    </PricingFrame>
  )
}

export default DevPricing
