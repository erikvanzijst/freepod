import { Button, IconButton, Stack, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material'
import ChevronLeftRoundedIcon from '@mui/icons-material/ChevronLeftRounded'
import ChevronRightRoundedIcon from '@mui/icons-material/ChevronRightRounded'
import { periodRange, periodTitle, shiftAnchor, type UsagePeriod } from './usageModel'

const PERIODS: { value: UsagePeriod; label: string }[] = [
  { value: 'day', label: 'Day' },
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
  { value: 'year', label: 'Year' },
]

interface UsagePeriodControlsProps {
  period: UsagePeriod
  anchor: Date
  now: Date
  onChange: (period: UsagePeriod, anchor: Date) => void
}

/** Which period is shown, and paging through it. Never pages into the future. */
export function UsagePeriodControls({ period, anchor, now, onChange }: UsagePeriodControlsProps) {
  const range = periodRange(period, anchor)
  const isCurrent = range.start <= now && now < range.end
  return (
    <Stack direction="row" alignItems="center" spacing={1} useFlexGap flexWrap="wrap">
      <ToggleButtonGroup
        size="small"
        exclusive
        value={period}
        // Switching period starts at the present; drilling into a bar is how
        // to reach a specific one.
        onChange={(_, value: UsagePeriod | null) => value && onChange(value, now)}
        aria-label="Period"
      >
        {PERIODS.map((p) => (
          <ToggleButton key={p.value} value={p.value} sx={{ px: 1.5 }}>
            {p.label}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
      <Stack direction="row" alignItems="center">
        <Tooltip title={`Previous ${period}`}>
          <IconButton size="small" onClick={() => onChange(period, shiftAnchor(period, anchor, -1))}>
            <ChevronLeftRoundedIcon />
          </IconButton>
        </Tooltip>
        <Typography sx={{ minWidth: 150, textAlign: 'center', fontWeight: 600 }}>
          {periodTitle(period, range)}
        </Typography>
        <Tooltip title={`Next ${period}`}>
          <span>
            <IconButton
              size="small"
              disabled={range.end > now}
              onClick={() => onChange(period, shiftAnchor(period, anchor, 1))}
            >
              <ChevronRightRoundedIcon />
            </IconButton>
          </span>
        </Tooltip>
      </Stack>
      {!isCurrent && (
        <Button size="small" onClick={() => onChange(period, now)}>
          Current {period}
        </Button>
      )}
    </Stack>
  )
}
