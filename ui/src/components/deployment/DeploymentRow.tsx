import { useState } from 'react'
import { Box, Button, Collapse, LinearProgress, Stack, Typography } from '@mui/material'
import ExpandMoreRounded from '@mui/icons-material/ExpandMoreRounded'
import TuneRounded from '@mui/icons-material/TuneRounded'
import FolderOutlined from '@mui/icons-material/FolderOutlined'
import StorageOutlined from '@mui/icons-material/StorageOutlined'
import DeleteOutlineRounded from '@mui/icons-material/DeleteOutlineRounded'
import { fg, line } from '../landing/landingTokens'
import AppIcon from '../apppage/AppIcon'
import { CopyButton } from '../CopyButton'
import { deploymentView, toneColor } from './deploymentView'
import { ProblemNotice, StatusLine, OpenButton, type DeploymentCardProps } from './DeploymentParts'
import { useDeploymentAccess } from './useDeploymentAccess'

/** A deployment as a row like the catalog's; it expands in place to everything else about the app. */
export function DeploymentRow({ deployment, userId, deletePending, onEdit, onDelete }: DeploymentCardProps) {
  const view = deploymentView(deployment)
  const [open, setOpen] = useState(Boolean(view.problem))
  const access = useDeploymentAccess(userId, deployment, open)

  const facts = [
    { label: 'Plan', value: view.planLine },
    { label: 'Version', value: view.version },
    { label: 'Added', value: view.since },
  ].filter((f) => f.value)

  return (
    <Box sx={{ position: 'relative', borderBottom: `1px solid ${line.soft}` }}>
      <Stack direction="row" alignItems="center" spacing={{ xs: 1.75, sm: 2.5 }} sx={{ py: 2, px: 1 }}>
        <Box
          component="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          sx={{ display: 'flex', alignItems: 'center', gap: { xs: 1.75, sm: 2.5 }, flex: 1, minWidth: 0, p: 0, border: 0, background: 'none', color: 'inherit', font: 'inherit', textAlign: 'left', cursor: 'pointer' }}
        >
          <AppIcon name={view.appName} src={view.iconUrl} size={48} />
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              alignItems={{ xs: 'flex-start', sm: 'center' }}
              spacing={{ xs: 0.25, sm: 1.5 }}
              sx={{ minWidth: 0 }}
            >
              <Typography noWrap sx={{ fontWeight: 600, fontSize: 17 }}>{view.appName}</Typography>
              <StatusLine view={view} size={13.5} />
            </Stack>
            <Typography noWrap sx={{ fontSize: 14, color: fg.faint }}>{view.address}</Typography>
          </Box>
          <Box sx={{ display: { xs: 'none', md: 'block' }, textAlign: 'right' }}>
            <Typography sx={{ fontSize: 14, color: fg.muted, whiteSpace: 'nowrap' }}>{view.planLine}</Typography>
            {view.versionLabel && <Typography sx={{ fontSize: 13, color: fg.faint, whiteSpace: 'nowrap' }}>{view.versionLabel}</Typography>}
          </Box>
          <ExpandMoreRounded sx={{ color: fg.faint, transition: 'transform 0.2s', transform: open ? 'rotate(180deg)' : 'none' }} />
        </Box>
        <OpenButton view={view} />
      </Stack>
      {view.status.progress && <LinearProgress sx={{ position: 'absolute', left: 0, right: 0, bottom: -1, height: 2 }} />}

      <Collapse in={open} unmountOnExit>
        <Stack spacing={2.5} sx={{ pl: { xs: 1, sm: 10 }, pr: 1, pb: 3 }}>
          {view.status.hint && <Typography sx={{ fontSize: 14, color: fg.muted }}>{view.status.hint}</Typography>}
          {view.problem && <ProblemNotice problem={view.problem} />}

          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', sm: 'repeat(4, auto)' }, justifyContent: 'start', columnGap: 5, rowGap: 2 }}>
            {view.address && (
              <Box sx={{ gridColumn: { xs: '1 / -1', sm: 'auto' } }}>
                <Typography sx={{ fontSize: 12.5, color: fg.faint }}>Address</Typography>
                <Stack direction="row" alignItems="center" spacing={0.25}>
                  <Typography sx={{ fontSize: 14.5 }}>{view.address}</Typography>
                  <CopyButton value={view.url!} label="address" />
                </Stack>
              </Box>
            )}
            {facts.map((f) => (
              <Box key={f.label}>
                <Typography sx={{ fontSize: 12.5, color: fg.faint }}>{f.label}</Typography>
                <Typography sx={{ fontSize: 14.5, lineHeight: '34px' }}>{f.value}</Typography>
              </Box>
            ))}
          </Box>

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {view.canEdit && (
              <Button variant="outlined" size="small" startIcon={<TuneRounded />} onClick={() => onEdit(deployment)}>Settings</Button>
            )}
            {access.files && <Button variant="outlined" size="small" startIcon={<FolderOutlined />} onClick={access.files} title="Browse and download (read-only)">Files</Button>}
            {access.database && <Button variant="outlined" size="small" startIcon={<StorageOutlined />} onClick={access.database}>Database</Button>}
            <Box sx={{ flex: 1 }} />
            {view.canRemove && (
              <Button size="small" startIcon={<DeleteOutlineRounded />} disabled={deletePending} onClick={() => onDelete(deployment)} sx={{ color: toneColor.problem }}>
                {deletePending ? 'Removing…' : 'Remove app'}
              </Button>
            )}
          </Stack>
        </Stack>
      </Collapse>
      {access.dialogs}
    </Box>
  )
}
