import { Box, MenuItem, Stack, TextField, Typography } from '@mui/material'
import SwapVertRounded from '@mui/icons-material/SwapVertRounded'
import { fg } from '../landing/landingTokens'
import { SearchField } from '../appsgallery/GalleryParts'
import { sortOptions, type SortKey } from './useDeploymentFilter'

interface DeploymentToolbarProps {
  search: string
  onSearch: (value: string) => void
  sort: SortKey
  onSort: (value: SortKey) => void
  shown: number
  total: number
  /** Whether "/" focuses this search; off while the catalog panel has its own. */
  slashShortcut?: boolean
}

/** Search and sort above the user's apps. */
export function DeploymentToolbar({ search, onSearch, sort, onSort, shown, total, slashShortcut = true }: DeploymentToolbarProps) {
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'center' }}>
      <Box sx={{ flex: 1, maxWidth: { sm: 520 } }}>
        <SearchField value={search} onChange={onSearch} placeholder="Search your apps…" fullWidth slashShortcut={slashShortcut} />
      </Box>
      <Box sx={{ flex: 1, display: { xs: 'none', sm: 'block' } }} />
      <Stack direction="row" spacing={1.5} alignItems="center" justifyContent="space-between">
        <Typography sx={{ fontSize: 13.5, color: fg.faint, whiteSpace: 'nowrap' }}>
          {search ? `${shown} of ${total}` : `${total} ${total === 1 ? 'app' : 'apps'}`}
        </Typography>
        <TextField
          select
          size="small"
          value={sort}
          onChange={(e) => onSort(e.target.value as SortKey)}
          aria-label="Sort"
          slotProps={{
            input: { startAdornment: <SwapVertRounded sx={{ fontSize: 18, color: fg.faint, mr: 1 }} /> },
            select: { MenuProps: { disableScrollLock: true } },
          }}
          sx={{ minWidth: 200, '& .MuiOutlinedInput-root': { height: 44, borderRadius: 999 } }}
        >
          {sortOptions.map((o) => (
            <MenuItem key={o.key} value={o.key}>
              {o.label}
            </MenuItem>
          ))}
        </TextField>
      </Stack>
    </Stack>
  )
}

