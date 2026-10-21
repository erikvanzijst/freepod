import { Box, LinearProgress, Stack, Typography } from '@mui/material'
import { resolveApiPath } from '../../api/client'
import { AppIcon } from '../apppage/AppIcon'
import { compareCategories, fg, line, MONO, SANS } from './landingTokens'
import { useLandingProducts, type ProductSummary } from './useLandingProducts'

/** The address label a visitor might give an app of each category. */
const labels: Record<string, string> = {
  photos: 'photos',
  'files & documents': 'files',
  'passwords & passkeys': 'vault',
  'chat & messaging': 'chat',
  'knowledge & wikis': 'wiki',
  'team collaboration': 'team',
  'forums & communities': 'forum',
}

const NAME = 'alex'

/** One app per category, in the order the catalog lists them, up to four. */
function pickApps(products: ProductSummary[]): ProductSummary[] {
  const seen = new Set<string>()
  return [...products]
    .sort((a, b) => compareCategories(a.category ?? '', b.category ?? ''))
    .filter((p) => {
      if (!p.category || seen.has(p.category)) return false
      seen.add(p.category)
      return true
    })
    .slice(0, 4)
}

/**
 * An illustration of a pod: one catalog app for each of the most familiar uses,
 * named by that use, each at its own address under one name, the last one still
 * setting up.
 */
export function PodPreview() {
  const { data = [] } = useLandingProducts()
  const apps = pickApps(data)

  return (
    <Box
      aria-hidden
      sx={{
        position: 'relative',
        borderRadius: '14px',
        border: `1px solid rgba(255,255,255,0.1)`,
        background: 'linear-gradient(170deg, rgba(20,27,52,0.92), rgba(11,16,32,0.94))',
        boxShadow: '0 40px 90px rgba(3,6,18,0.65), 0 0 0 1px rgba(124,91,255,0.08)',
        overflow: 'hidden',
        minHeight: 340,
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1.25} sx={{ px: 2.5, py: 1.75, borderBottom: `1px solid ${line.soft}` }}>
        {['#F87171', '#FBBF24', '#34D399'].map((c) => (
          <Box key={c} sx={{ width: 9, height: 9, borderRadius: '50%', background: c, opacity: 0.55 }} />
        ))}
        <Typography sx={{ fontFamily: MONO, fontSize: 12.5, color: fg.faint, pl: 1 }}>{NAME}.freepod.app</Typography>
      </Stack>

      <Box sx={{ px: 2.5, pt: 2.25, pb: 1 }}>
        <Typography sx={{ fontFamily: SANS, fontSize: 12, letterSpacing: '0.14em', textTransform: 'uppercase', color: fg.faint }}>
          Your apps
        </Typography>
      </Box>

      {apps.map((app, i) => {
        const settingUp = i === apps.length - 1 && apps.length > 1
        const label = labels[(app.category ?? '').toLowerCase()] ?? app.slug ?? app.name.toLowerCase()
        return (
          <Box key={app.id} sx={{ position: 'relative', borderTop: i ? `1px solid ${line.softer}` : 'none' }}>
            <Stack direction="row" alignItems="center" spacing={1.75} sx={{ px: 2.5, py: 1.6 }}>
              <AppIcon name={app.name} src={app.iconUrl ? resolveApiPath(app.iconUrl) : null} size={38} />
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography noWrap sx={{ fontFamily: SANS, fontWeight: 600, fontSize: 15, color: fg.primary }}>{app.category}</Typography>
                <Typography noWrap sx={{ fontFamily: SANS, fontSize: 13, color: fg.faint }}>
                  {label}-{NAME}.freepod.app
                </Typography>
              </Box>
              <Stack direction="row" alignItems="center" spacing={0.75}>
                <Box sx={{ width: 7, height: 7, borderRadius: '50%', background: settingUp ? '#38BDF8' : '#22C55E' }} />
                <Typography sx={{ fontFamily: SANS, fontSize: 13, color: fg.muted, whiteSpace: 'nowrap' }}>
                  {settingUp ? 'Setting up' : 'Running'}
                </Typography>
              </Stack>
            </Stack>
            {settingUp && <LinearProgress sx={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: 2 }} />}
          </Box>
        )
      })}
    </Box>
  )
}

export default PodPreview
