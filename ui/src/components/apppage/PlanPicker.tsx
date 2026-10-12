import { Box, Stack, Typography } from '@mui/material'
import { accent, fg, line, SANS } from '../landing/landingTokens'
import type { ListingPlan } from './listing'
import { planPrice, planSummary } from './listingFormat'

interface PlanPickerProps {
  plans: ListingPlan[]
  selected: number
  onSelect: (index: number) => void
}

/** Compact radio list of plans, for a booking-style sidebar card. */
export function PlanPicker({ plans, selected, onSelect }: PlanPickerProps) {
  return (
    <Stack spacing={1} role="radiogroup" aria-label="Plan">
      {plans.map((plan, i) => {
        const active = i === selected
        return (
          <Stack
            key={plan.name}
            role="radio"
            aria-checked={active}
            tabIndex={0}
            direction="row"
            alignItems="center"
            spacing={1.5}
            onClick={() => onSelect(i)}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onSelect(i)}
            sx={{
              px: 2,
              py: 1.1,
              borderRadius: '12px',
              cursor: 'pointer',
              border: `1px solid ${active ? accent.blue : line.soft}`,
              background: active ? 'rgba(91,140,255,0.1)' : 'transparent',
              transition: 'border-color 0.2s, background 0.2s',
              '&:hover': { borderColor: active ? accent.blue : 'rgba(148,163,184,0.35)' },
            }}
          >
            <Box
              sx={{
                width: 18,
                height: 18,
                borderRadius: '50%',
                border: `2px solid ${active ? accent.blue : fg.faint}`,
                display: 'grid',
                placeItems: 'center',
              }}
            >
              {active && <Box sx={{ width: 8, height: 8, borderRadius: '50%', background: accent.blue }} />}
            </Box>
            <Box sx={{ flex: 1 }}>
              <Stack direction="row" alignItems="center" spacing={1}>
                <Typography sx={{ fontFamily: SANS, fontWeight: 600, fontSize: 15 }}>{plan.name}</Typography>
              </Stack>
              <Typography sx={{ fontSize: 13, color: fg.faint }}>{planSummary(plan)}</Typography>
            </Box>
            <Typography sx={{ fontFamily: SANS, fontWeight: 600, fontSize: 15 }}>
              {planPrice(plan)}
              {plan.priceCents > 0 && (
                <Box component="span" sx={{ fontWeight: 400, fontSize: 12.5, color: fg.faint }}>/mo</Box>
              )}
            </Typography>
          </Stack>
        )
      })}
    </Stack>
  )
}
