import type { ReactNode } from 'react'
import { Box, Container, Slider, Stack, Typography } from '@mui/material'
import SectionHeading from '../SectionHeading'
import Reveal from '../Reveal'
import { accent, DISPLAY, fg, line, MONO, SANS } from '../landingTokens'
import { euro, eyebrowSx, hourlyPrice, monthlyPrice, pricingNotes, rates, type ResourceRate } from './devPricing'
import { buildsColor, formatLevel, presets, toLevel, toPos, type Estimate } from './useEstimate'

export function PresetChips({ estimate }: { estimate: Estimate }) {
  return (
    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
      {presets.map((p) => {
        const selected = p.label === estimate.preset
        return (
          <Box
            key={p.label}
            component="button"
            onClick={() => estimate.choose(p.label)}
            aria-pressed={selected}
            sx={{
              all: 'unset',
              cursor: 'pointer',
              px: 1.5,
              py: 0.6,
              borderRadius: 999,
              fontFamily: SANS,
              fontSize: 14,
              color: selected ? fg.primary : fg.muted,
              background: selected ? 'rgba(91,140,255,0.16)' : 'rgba(255,255,255,0.04)',
              border: `1px solid ${selected ? 'rgba(91,140,255,0.5)' : 'rgba(255,255,255,0.08)'}`,
              '&:hover': { color: fg.primary },
              '&:focus-visible': { outline: `2px solid ${accent.blue}`, outlineOffset: 2 },
            }}
          >
            {p.label}
          </Box>
        )
      })}
    </Stack>
  )
}

export function UsageSlider({ rate, estimate }: { rate: ResourceRate; estimate: Estimate }) {
  return (
    <Slider
      aria-label={rate.name}
      value={toPos(rate.id, estimate.usage[rate.id])}
      onChange={(_, v) => estimate.set(rate.id, toLevel(rate.id, v as number))}
      sx={{
        color: rate.color,
        height: 4,
        '& .MuiSlider-rail': { background: line.soft, opacity: 1 },
        '& .MuiSlider-thumb': { width: 16, height: 16, boxShadow: `0 0 0 4px ${rate.color}33` },
      }}
    />
  )
}

/** The four unit prices, one row each, filling the height they are given. A rate with a floor is marked for a footnote. */
export function RateRows({ px = 3 }: { px?: number }) {
  return (
    <>
      {rates.map((rate) => {
        const Icon = rate.icon
        return (
          <Stack key={rate.id} direction="row" alignItems="center" spacing={1.75} sx={{ px, py: 2.25, flex: 1, borderTop: `1px solid ${line.softer}` }}>
            <Stack
              sx={{
                flexShrink: 0,
                width: 38,
                height: 38,
                borderRadius: '10px',
                alignItems: 'center',
                justifyContent: 'center',
                background: `${rate.color}1f`,
                border: `1px solid ${rate.color}3a`,
              }}
            >
              <Icon sx={{ fontSize: 20, color: rate.color }} />
            </Stack>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography sx={{ fontFamily: SANS, fontWeight: 600, fontSize: 16 }}>
                {rate.name}
                {rate.floor > 0 && (
                  <Box component="sup" aria-hidden sx={{ color: fg.faint, fontWeight: 400, ml: 0.25 }}>
                    *
                  </Box>
                )}
              </Typography>
              <Typography sx={{ fontFamily: MONO, fontSize: 11.5, color: fg.faint }}>{hourlyPrice(rate)} per hour</Typography>
            </Box>
            <Box sx={{ textAlign: 'right' }}>
              <Typography sx={{ fontFamily: DISPLAY, fontWeight: 500, fontSize: 30, lineHeight: 1.1, letterSpacing: '-0.02em' }}>
                {monthlyPrice(rate)}
              </Typography>
              <Typography sx={{ fontFamily: SANS, fontSize: 12.5, color: fg.faint }}>per {rate.unit} · month</Typography>
            </Box>
          </Stack>
        )
      })}
    </>
  )
}

/** One slider per resource with its level and cost, then the preset's builds. */
export function EstimateSliders({ estimate }: { estimate: Estimate }) {
  return (
    <Stack spacing={2}>
      {estimate.costs.map(({ rate, cost }) => (
        <Box key={rate.id}>
          <Stack direction="row" alignItems="baseline" spacing={1}>
            <Typography sx={{ fontFamily: SANS, fontWeight: 600, fontSize: 15, flex: 1 }}>{rate.name}</Typography>
            <Typography sx={{ fontFamily: MONO, fontSize: 13, color: fg.primary }}>{formatLevel(rate, estimate.usage[rate.id])}</Typography>
          </Stack>
          <Stack direction="row" alignItems="center" spacing={2.5}>
            <UsageSlider rate={rate} estimate={estimate} />
            <Typography sx={{ fontFamily: MONO, fontSize: 13, color: fg.muted, minWidth: 64, textAlign: 'right' }}>{euro(cost, 3)}</Typography>
          </Stack>
        </Box>
      ))}
      {estimate.builds > 0 && (
        <Stack direction="row" alignItems="center" spacing={1}>
          <Box sx={{ width: 8, height: 8, borderRadius: '50%', background: buildsColor }} />
          <Typography sx={{ fontFamily: SANS, fontSize: 14, color: fg.muted, flex: 1 }}>{estimate.buildCount} builds a month</Typography>
          <Typography sx={{ fontFamily: MONO, fontSize: 13, color: fg.muted }}>{euro(estimate.builds, 3)}</Typography>
        </Stack>
      )}
    </Stack>
  )
}

/** The estimate's footer: what the preset is, and the monthly total. */
export function EstimateTotal({ estimate, label = 'Per month' }: { estimate: Estimate; label?: string }) {
  return (
    <Stack
      direction="row"
      alignItems="flex-end"
      justifyContent="space-between"
      spacing={2}
      sx={{ px: { xs: 2.5, md: 3.5 }, py: 2.5, borderTop: `1px solid ${line.soft}`, background: 'rgba(7,10,20,0.35)' }}
    >
      <Box>
        <Typography sx={eyebrowSx}>{label}</Typography>
        <Typography sx={{ fontFamily: SANS, fontSize: 13.5, color: fg.muted, mt: 0.5 }}>{estimate.note}</Typography>
      </Box>
      <Typography sx={{ fontFamily: DISPLAY, fontWeight: 500, fontSize: { xs: 40, md: 52 }, lineHeight: 1, letterSpacing: '-0.03em' }}>
        {euro(estimate.total)}
      </Typography>
    </Stack>
  )
}

/** Builds and traffic, as two short columns. */
export function PricingNotes() {
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: { xs: 2.5, md: 4 } }}>
      {[
        ['Builds', pricingNotes.builds],
        ['Traffic', pricingNotes.traffic],
      ].map(([title, body]) => (
        <Box key={title}>
          <Typography sx={{ fontFamily: MONO, fontSize: 12, letterSpacing: '0.14em', textTransform: 'uppercase', color: accent.cyan }}>
            {title}
          </Typography>
          <Typography sx={{ fontFamily: SANS, fontSize: 15, lineHeight: 1.6, color: fg.muted, mt: 0.75 }}>{body}</Typography>
        </Box>
      ))}
    </Box>
  )
}

/** The pricing section around a layout: heading above, small print and notes below. */
export function PricingFrame({ children }: { children: ReactNode }) {
  return (
    <Box component="section" id="pricing" sx={{ py: { xs: 9, md: 14 }, scrollMarginTop: 80 }}>
      <Container maxWidth="lg">
        <SectionHeading
          eyebrow="Pricing"
          title="Pay for what you use."
          subtitle="Your apps are billed by the hour for the CPU, memory and storage they use."
        />
        <Box sx={{ mt: { xs: 6, md: 8 } }}>{children}</Box>
        <Typography sx={{ fontFamily: SANS, fontSize: 13, color: fg.faint, mt: 1.5, textAlign: 'right' }}>
          Averages over a 730-hour month. {pricingNotes.disclaimer}
        </Typography>
        <Reveal delay={80}>
          <Box sx={{ mt: { xs: 5, md: 6 } }}>
            <PricingNotes />
          </Box>
        </Reveal>
      </Container>
    </Box>
  )
}
