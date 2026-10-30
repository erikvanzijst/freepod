import { ToggleButton, ToggleButtonGroup } from '@mui/material'
import type { AccessFilter } from './accessText'

const OPTIONS: { value: AccessFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'signed-in', label: 'Signed in' },
  { value: 'not-yet', label: 'Not yet' },
]

export function AccessFilterChips({ value, onChange }: { value: AccessFilter; onChange: (v: AccessFilter) => void }) {
  return (
    <ToggleButtonGroup
      exclusive
      size="small"
      value={value}
      onChange={(_e, v: AccessFilter | null) => v && onChange(v)}
      aria-label="Filter"
      sx={{ gap: 0.75, '& .MuiToggleButton-root': { border: '1px solid rgba(148,163,184,0.3) !important', borderRadius: '999px !important', px: 1.5, textTransform: 'none', whiteSpace: 'nowrap' } }}
    >
      {OPTIONS.map((o) => (
        <ToggleButton key={o.value} value={o.value}>{o.label}</ToggleButton>
      ))}
    </ToggleButtonGroup>
  )
}
