import { useEffect, useMemo, useState } from 'react'
import { Box, Button, Dialog, DialogActions, DialogContent, Divider, LinearProgress, Typography } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Deployment, Plan } from '../api/types'
import { ApiError } from '../api/client'
import { deleteDeployment, getDeployment, updateDeployment } from '../api/endpoints'
import { isTransitionalStatus } from '../utils/deploymentStatus'
import { formatLocalIso, parseUtc } from '../utils/formatDate'
import { ConfirmDeleteDialog } from './ConfirmDeleteDialog'
import { DeployDialogContent } from './DeployDialogContent'
import { DatabasePanel } from './DatabasePanel'
import { SftpAccessPanel } from './SftpAccessPanel'

interface DeploymentDialogProps {
  deployment: Deployment | null
  onClose: () => void
}

function formatAge(value: string | null | undefined): string {
  if (!value) return '—'
  const ms = Date.now() - parseUtc(value).getTime()
  const seconds = Math.floor(ms / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)

  if (days > 0) return `${days}d ${hours % 24}h`
  if (hours > 0) return `${hours}h ${minutes % 60}m`
  if (minutes > 0) return `${minutes}m`
  return 'just now'
}

function MetadataRow({ label, value }: { label: string; value: string }) {
  return (
    <Box sx={{ display: 'flex', gap: 1 }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
        {label}
      </Typography>
      <Typography variant="body2">{value}</Typography>
    </Box>
  )
}

export function DeploymentDialog({ deployment: initialDeployment, onClose }: DeploymentDialogProps) {
  const queryClient = useQueryClient()
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  // Poll the single deployment while the dialog is open
  const { data: polledDeployment, error: pollError } = useQuery({
    queryKey: ['deployment', initialDeployment?.user_id, initialDeployment?.id],
    queryFn: () => getDeployment(initialDeployment!.user_id, initialDeployment!.id),
    enabled: Boolean(initialDeployment),
    initialData: initialDeployment ?? undefined,
    retry: (_count, error) => !(error instanceof ApiError && error.status === 404),
    refetchInterval: (query) => {
      if (query.state.error) return false
      const d = query.state.data
      return d && isTransitionalStatus(d.status) ? 1000 : false
    },
  })

  // Handle 404 — deployment was deleted, remove from list and close
  useEffect(() => {
    if (!(pollError instanceof ApiError && pollError.status === 404)) return
    if (initialDeployment) {
      queryClient.setQueryData<Deployment[]>(['admin-deployments'], (old) =>
        old?.filter((d) => d.id !== initialDeployment.id),
      )
    }
    onClose()
  }, [pollError, initialDeployment, queryClient, onClose])

  // Patch the admin-deployments list cache whenever the polled deployment changes
  useEffect(() => {
    if (!polledDeployment) return
    queryClient.setQueryData<Deployment[]>(['admin-deployments'], (old) =>
      old?.map((d) => d.id === polledDeployment.id ? polledDeployment : d),
    )
  }, [polledDeployment, queryClient])

  const deployment = polledDeployment ?? initialDeployment

  const template = deployment?.applied_template ?? deployment?.desired_template
  const product = template?.product
  const appliedId = deployment?.applied_template?.id
  const canonicalId = deployment?.applied_template?.product?.template_id
  const isUpToDate = appliedId != null && canonicalId != null && appliedId === canonicalId
  const isTransitioning = isTransitionalStatus(deployment?.status)
  const isDeleting = deployment?.status === 'deleting'

  const upgradeMutation = useMutation({
    mutationFn: () =>
      updateDeployment(deployment!.user_id, deployment!.id, {
        desired_template_id: canonicalId!,
        user_values_json: deployment!.user_values_json ?? undefined,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['deployment', updated.user_id, updated.id], updated)
      queryClient.setQueryData<Deployment[]>(['admin-deployments'], (old) =>
        old?.map((d) => d.id === updated.id ? updated : d),
      )
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteDeployment(deployment!.user_id, deployment!.id),
    onSuccess: () => {
      // Refetch the single deployment to pick up the 'deleting' status and start polling
      queryClient.invalidateQueries({ queryKey: ['deployment', deployment!.user_id, deployment!.id] })
    },
  })

  const subscriptionPlan: Plan[] = useMemo(() => {
    const plan = deployment?.subscription?.plan_template?.plan
    if (!plan) return []
    return [{ ...plan, template: deployment?.subscription?.plan_template ?? null }]
  }, [deployment])

  if (!deployment) return null

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogContent>
        {product && template && (
          <DeployDialogContent
            product={product}
            valuesSchemaJson={template.values_schema_json ?? null}
            initialValuesJson={deployment.user_values_json ?? null}
            onChange={() => {}}
            initialHostname={deployment.hostname ?? undefined}
            readOnly
            plans={subscriptionPlan}
            selectedPlanTemplateId={deployment.subscription?.plan_template?.id ?? null}
          />
        )}
        {isTransitioning && (
          <LinearProgress
            color={isDeleting ? 'secondary' : 'primary'}
            sx={{ my: 2, borderRadius: 1 }}
          />
        )}
        <Divider sx={{ my: 2 }} />
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          <MetadataRow label="Plan" value={deployment.subscription?.plan_template?.plan?.name ?? '—'} />
          <MetadataRow label="Owner" value={deployment.user?.email ?? '—'} />
          <MetadataRow label="Created" value={formatLocalIso(deployment.created_at)} />
          <MetadataRow label="Age" value={formatAge(deployment.created_at)} />
          <MetadataRow label="Last reconciliation" value={formatLocalIso(deployment.last_reconcile_at)} />
          <MetadataRow label="Current template" value={deployment.applied_template ? `#${deployment.applied_template.id}` : '—'} />
          <MetadataRow label="Status" value={deployment.status ?? '—'} />
        </Box>
        <SftpAccessPanel userId={deployment.user_id} deploymentId={deployment.id} />
        <DatabasePanel userId={deployment.user_id} deploymentId={deployment.id} />
      </DialogContent>
      <DialogActions>
        <Button
          variant="outlined"
          color="error"
          disabled={isTransitioning || deleteMutation.isPending}
          onClick={() => setConfirmingDelete(true)}
        >
          {deleteMutation.isPending || isDeleting ? 'Deleting...' : 'Delete'}
        </Button>
        {confirmingDelete && (
          <ConfirmDeleteDialog
            name={product?.name ?? deployment.hostname ?? deployment.id}
            subject="deployment"
            onConfirm={() => {
              setConfirmingDelete(false)
              deleteMutation.mutate()
            }}
            onCancel={() => setConfirmingDelete(false)}
          />
        )}
        <Box sx={{ flex: 1 }} />
        <Button variant="outlined" onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          color="primary"
          disabled={isUpToDate || isTransitioning || upgradeMutation.isPending}
          onClick={() => upgradeMutation.mutate()}
        >
          {upgradeMutation.isPending || (isTransitioning && !isDeleting)
            ? 'Upgrading...'
            : isUpToDate
              ? 'Up to date'
              : `Upgrade to #${canonicalId}`}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
