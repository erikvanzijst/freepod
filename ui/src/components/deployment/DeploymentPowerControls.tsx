import { useState } from 'react'
import { Button, Stack, Typography } from '@mui/material'
import PlayCircleOutlined from '@mui/icons-material/PlayCircleOutlined'
import StopCircleOutlined from '@mui/icons-material/StopCircleOutlined'
import type { Deployment } from '../../api/types'
import { deploymentView, powerChanging, powerPhase } from './deploymentView'
import { StopAppDialog } from './StopAppDialog'
import { useDeploymentPower } from './useDeploymentPower'

interface DeploymentPowerControlsProps {
  deployment: Deployment
  onUpdated?: (updated: Deployment) => void
}

/** Stop or Start for one deployment, with the stop confirmed first and a refusal shown beside it. */
export function DeploymentPowerControls({ deployment, onUpdated }: DeploymentPowerControlsProps) {
  const view = deploymentView(deployment)
  const power = useDeploymentPower(deployment.user_id, deployment, onUpdated)
  const [confirmStop, setConfirmStop] = useState(false)
  const busy = power.pending || powerChanging(deployment)
  const phase = powerPhase(deployment)

  if (!view.canStop && !view.canStart) return null

  return (
    <Stack direction="row" alignItems="center" spacing={1}>
      {view.canStop ? (
        <Button variant="outlined" startIcon={<StopCircleOutlined />} disabled={busy} onClick={() => setConfirmStop(true)}>
          {power.pending ? 'Stopping...' : phase === 'starting' ? 'Starting...' : 'Stop'}
        </Button>
      ) : (
        <Button variant="outlined" startIcon={<PlayCircleOutlined />} disabled={busy} onClick={power.start}>
          {power.pending ? 'Starting...' : phase === 'stopping' ? 'Stopping...' : 'Start'}
        </Button>
      )}
      {power.error && (
        <Typography variant="body2" color="warning.main" role="alert">
          {power.error}
        </Typography>
      )}
      {confirmStop && (
        <StopAppDialog
          appName={view.appName}
          address={view.address}
          onCancel={() => setConfirmStop(false)}
          onConfirm={() => {
            setConfirmStop(false)
            power.stop()
          }}
        />
      )}
    </Stack>
  )
}
