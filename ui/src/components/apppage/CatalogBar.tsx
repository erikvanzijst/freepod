import { Autocomplete, Box, Container, InputAdornment, Stack, TextField, Typography } from '@mui/material'
import SearchRounded from '@mui/icons-material/SearchRounded'
import ChevronRightRounded from '@mui/icons-material/ChevronRightRounded'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import { resolveApiPath } from '../../api/client'
import { categoryIcon, fg, ink, line, SANS } from '../landing/landingTokens'
import { useLandingProducts } from '../landing/useLandingProducts'
import { appHref } from './appHref'

interface CatalogBarProps {
  trail: string[]
  /** Show the category chip row beneath the breadcrumb. */
  showCategories?: boolean
  activeCategory?: string
}

/** Jump straight to another app's page by name. */
export function AppSearch({ width = 280 }: { width?: number | string }) {
  const { data = [] } = useLandingProducts()
  const navigate = useNavigate()

  return (
    <Autocomplete
      size="small"
      options={data}
      getOptionLabel={(p) => p.name}
      onChange={(_, p) => p && navigate(appHref(p))}
      blurOnSelect
      clearOnBlur
      sx={{ width }}
      slotProps={{
        popper: { placement: 'bottom-end', sx: { minWidth: 340 } },
        paper: { sx: { background: ink.raised, border: `1px solid ${line.soft}` } },
      }}
      renderOption={({ key, ...props }, p) => (
        <Box component="li" key={key} {...props} sx={{ gap: 1.5 }}>
          <Box sx={{ width: 24, height: 24, flex: '0 0 auto' }}>
            {p.iconUrl && <Box component="img" src={resolveApiPath(p.iconUrl)} alt="" sx={{ width: 1, height: 1, objectFit: 'contain' }} />}
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontSize: 14.5, lineHeight: 1.3 }}>{p.name}</Typography>
            {p.replaces && (
              <Typography noWrap sx={{ fontSize: 12, lineHeight: 1.4, color: fg.faint }}>
                An alternative to {p.replaces}
              </Typography>
            )}
          </Box>
        </Box>
      )}
      renderInput={(params) => (
        <TextField
          {...params}
          placeholder="Search apps…"
          slotProps={{
            input: {
              ...params.InputProps,
              startAdornment: (
                <InputAdornment position="start">
                  <SearchRounded sx={{ fontSize: 20, color: fg.faint }} />
                </InputAdornment>
              ),
              sx: { borderRadius: 999, fontFamily: SANS, fontSize: 14.5 },
            },
          }}
        />
      )}
    />
  )
}

/** Secondary bar under the site nav: breadcrumb, app search, and categories. */
export function CatalogBar({ trail, showCategories = false, activeCategory }: CatalogBarProps) {
  const { data = [] } = useLandingProducts()
  const categories = [...new Set(data.map((p) => p.category).filter((c): c is string => !!c))]

  return (
    <Box sx={{ borderBottom: `1px solid ${line.softer}`, background: 'rgba(11,16,32,0.6)' }}>
      <Container maxWidth="lg">
        <Stack direction="row" alignItems="center" sx={{ minHeight: 60, gap: 2 }}>
          <Stack direction="row" alignItems="center" spacing={0.5} sx={{ flex: 1, minWidth: 0 }}>
            <Box component={RouterLink} to="/apps" sx={{ fontSize: 14, color: fg.muted, '&:hover': { color: fg.primary } }}>
              Apps
            </Box>
            {trail.map((crumb, i) => (
              <Stack key={crumb} direction="row" alignItems="center" spacing={0.5} sx={{ minWidth: 0 }}>
                <ChevronRightRounded sx={{ fontSize: 18, color: fg.faint }} />
                <Typography
                  noWrap
                  sx={{ fontSize: 14, color: i === trail.length - 1 ? fg.primary : fg.muted }}
                >
                  {crumb}
                </Typography>
              </Stack>
            ))}
          </Stack>
          <Box sx={{ display: { xs: 'none', sm: 'block' } }}>
            <AppSearch />
          </Box>
        </Stack>

        {showCategories && (
          <Stack
            direction="row"
            spacing={1}
            sx={{ pb: 1.75, overflowX: 'auto', scrollbarWidth: 'none', '&::-webkit-scrollbar': { display: 'none' } }}
          >
            {categories.map((category) => {
              const Icon = categoryIcon(category)
              const active = category === activeCategory
              return (
                <Box
                  key={category}
                  component={RouterLink}
                  to={`/apps?category=${encodeURIComponent(category)}`}
                  sx={{
                    flex: '0 0 auto',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 0.75,
                    px: 1.5,
                    py: 0.6,
                    borderRadius: 999,
                    fontSize: 13.5,
                    color: active ? fg.primary : fg.muted,
                    border: `1px solid ${active ? 'rgba(91,140,255,0.5)' : line.soft}`,
                    background: active ? 'rgba(91,140,255,0.12)' : 'transparent',
                    '&:hover': { color: fg.primary, borderColor: 'rgba(148,163,184,0.4)' },
                  }}
                >
                  <Icon sx={{ fontSize: 16 }} />
                  {category}
                </Box>
              )
            })}
          </Stack>
        )}
      </Container>
    </Box>
  )
}

export default CatalogBar
