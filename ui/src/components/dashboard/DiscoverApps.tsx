import { Box, Button, Drawer, IconButton, Stack, Typography } from '@mui/material'
import AddRounded from '@mui/icons-material/AddRounded'
import ArrowForwardRounded from '@mui/icons-material/ArrowForwardRounded'
import CloseRounded from '@mui/icons-material/CloseRounded'
import { cardSurface, DISPLAY, fg, line } from '../landing/landingTokens'
import AppIcon from '../apppage/AppIcon'
import { InstallFlow } from '../InstallFlow'
import { useGallery, useGalleryInstall, type GalleryApp } from '../appsgallery/useGallery'
import { CatalogList } from '../appsgallery/RowsLayout'

/** The last row of a deployments list: opens the catalog panel. */
export function AddAppRow({ onClick }: { onClick: () => void }) {
  return (
    <Box
      component="button"
      onClick={onClick}
      sx={{
        width: 1,
        display: 'flex',
        alignItems: 'center',
        gap: 2.5,
        py: 2,
        px: 1,
        border: 0,
        borderBottom: `1px solid ${line.soft}`,
        background: 'none',
        color: fg.muted,
        font: 'inherit',
        cursor: 'pointer',
        textAlign: 'left',
        '&:hover': { color: fg.primary },
      }}
    >
      <Box sx={{ width: 48, height: 48, borderRadius: '12px', display: 'grid', placeItems: 'center', border: `1.5px dashed ${line.soft}` }}>
        <AddRounded />
      </Box>
      <Typography sx={{ fontWeight: 600, fontSize: 16 }}>Add an app</Typography>
    </Box>
  )
}

/**
 * First-run state: nothing installed yet, so a few apps to start from and a
 * way into the full catalog.
 */
export function StarterApps({ onPick, onBrowse }: { onPick: (app: GalleryApp) => void; onBrowse: () => void }) {
  const apps = useGallery().apps.filter((app) => app.visibility === 'public')

  return (
    <Box sx={{ ...cardSurface, borderRadius: '12px', p: { xs: 3, md: 5 } }}>
      <Typography sx={{ fontFamily: DISPLAY, fontSize: { xs: 26, md: 32 }, fontWeight: 500, letterSpacing: '-0.01em' }}>
        Your pod is ready for its first app.
      </Typography>
      <Typography sx={{ mt: 1, color: fg.muted, fontSize: 16, maxWidth: 620 }}>
        Pick something you use every day. You can add more later, and export your data whenever you like.
      </Typography>

      <Box sx={{ mt: 4, display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 1.5 }}>
        {apps.slice(0, 4).map((app) => (
          <Stack
            key={app.id}
            component="button"
            onClick={() => onPick(app)}
            direction="row"
            spacing={2}
            alignItems="center"
            sx={{
              p: 2,
              background: 'none',
              cursor: 'pointer',
              font: 'inherit',
              textAlign: 'left',
              borderRadius: '10px',
              border: `1px solid ${line.softer}`,
              color: 'inherit',
              textDecoration: 'none',
              '&:hover': { borderColor: 'rgba(148,163,184,0.35)', background: 'rgba(255,255,255,0.025)' },
            }}
          >
            <AppIcon name={app.name} src={app.iconUrl ?? null} size={44} />
            <Box sx={{ minWidth: 0 }}>
              <Typography sx={{ fontWeight: 600 }}>{app.name}</Typography>
              <Typography sx={{ fontSize: 14, color: fg.muted }}>{app.tagline}</Typography>
            </Box>
          </Stack>
        ))}
      </Box>

      <Button onClick={onBrowse} endIcon={<ArrowForwardRounded />} sx={{ mt: 3, textTransform: 'none', fontSize: 15 }}>
        Browse all {apps.length} apps
      </Button>
    </Box>
  )
}

/** The catalog in a side panel, so installing never leaves the dashboard. */
export function AddAppDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const g = useGallery()
  const { install, flow, close } = useGalleryInstall(() => {})

  return (
    <>
      <Drawer
        anchor="right"
        open={open}
        onClose={onClose}
        slotProps={{
          paper: {
            sx: {
              width: { xs: '100vw', md: 820 },
              background: '#0B1020',
              borderLeft: `1px solid ${line.soft}`,
              backgroundImage: 'none',
            },
          },
        }}
      >
        <Box sx={{ px: { xs: 2, md: 4 }, pt: 3, pb: 8 }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 3 }}>
            <Typography sx={{ fontFamily: DISPLAY, fontSize: 30, fontWeight: 500 }}>Add an app</Typography>
            <IconButton aria-label="Close" onClick={onClose} sx={{ color: fg.muted }}>
              <CloseRounded />
            </IconButton>
          </Stack>
          <CatalogList g={g} onInstall={install} />
        </Box>
      </Drawer>
      {flow && <InstallFlow product={flow.product} plan={flow.plan} onClose={close} onLaunched={onClose} />}
    </>
  )
}
