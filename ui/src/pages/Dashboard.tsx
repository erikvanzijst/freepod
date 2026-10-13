import {
  Box,
  Button,
  Card,
  Grid,
  Stack,
  Typography,
} from '@mui/material'
import AddRounded from '@mui/icons-material/AddRounded'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  deleteDeployment,
  listDeployments,
} from '../api/endpoints'
import type { Deployment } from '../api/types'
import { useAuth } from '../state/AuthContext'
import { isTransitionalStatus } from '../utils/deploymentStatus'
import { DeployDialog } from '../components/DeployDialog'
import { ConfirmDeleteDialog } from '../components/ConfirmDeleteDialog'
import { PageHeading } from '../components/PageHeading'
import { ClaimSubdomain } from '../components/subdomain/ClaimSubdomain'
import { ClaimSubdomainBanner } from '../components/subdomain/ClaimSubdomainBanner'
import { useMySubdomain } from '../components/subdomain/useMySubdomain'
import { AddAppDrawer, AddAppRow, StarterApps } from '../components/dashboard/DiscoverApps'
import type { GalleryApp } from '../components/appsgallery/useGallery'
import { DeploymentRow } from '../components/deployment/DeploymentRow'
import type { DeploymentCardProps } from '../components/deployment/DeploymentParts'
import { DeploymentToolbar } from '../components/deployment/DeploymentToolbar'
import { useDeploymentFilter } from '../components/deployment/useDeploymentFilter'

function Dashboard() {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const [deletePendingIds, setDeletePendingIds] = useState<Set<string>>(new Set())
  const [editDeployment, setEditDeployment] = useState<Deployment | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Deployment | null>(null)
  // Session state only: dismissing is not an answer, so it is not recorded
  // anywhere and the invitation returns on reload.
  const [invitationDismissed, setInvitationDismissed] = useState(false)
  const [, setParams] = useSearchParams()
  const [drawerOpen, setDrawerOpen] = useState(false)

  const subdomainQuery = useMySubdomain()
  const holdsSubdomain = Boolean(subdomainQuery.data?.subdomain)
  const platformDomain = subdomainQuery.data?.domain ?? ''

  const deploymentsQuery = useQuery({
    queryKey: ['deployments', user?.id],
    queryFn: () => listDeployments(user!.id),
    enabled: Boolean(user?.id),
    refetchInterval: (query) => {
      const items = query.state.data ?? []
      return items.some((deployment) => isTransitionalStatus(deployment.status)) ? 3000 : false
    },
  })

  const deleteDeploymentMutation = useMutation({
    mutationFn: (deploymentId: string) =>
      deleteDeployment(user!.id, deploymentId),
    onMutate: (deploymentId) => {
      setDeletePendingIds((previous) => new Set(previous).add(deploymentId))
      return { deploymentId }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['deployments'] }),
    onError: (_error, deploymentId) => {
      setDeletePendingIds((previous) => {
        const next = new Set(previous)
        next.delete(deploymentId)
        return next
      })
    },
  })

  useEffect(() => {
    const visibleIds = new Set((deploymentsQuery.data ?? []).map((deployment) => deployment.id))
    setDeletePendingIds((previous) => {
      let changed = false
      const next = new Set<string>()
      previous.forEach((id) => {
        if (visibleIds.has(id)) {
          next.add(id)
        } else {
          changed = true
        }
      })
      return changed ? next : previous
    })
  }, [deploymentsQuery.data])

  const deployments = deploymentsQuery.data ?? []
  const showEmpty = !deploymentsQuery.isLoading && deployments.length === 0
  const filter = useDeploymentFilter(deployments)
  const shown = filter.results

  // The catalog panel's search, filter and expanded row live in the URL while it is open.
  const openCatalog = (app?: GalleryApp) => {
    if (app) setParams((current) => { const next = new URLSearchParams(current); next.set('open', app.href); return next }, { replace: true })
    setDrawerOpen(true)
  }
  const closeCatalog = () => {
    setDrawerOpen(false)
    setParams((current) => {
      const next = new URLSearchParams(current)
      // One update for everything the panel put in the URL, its install request
      // included: React Router builds each update from the last rendered URL, so
      // a second update in the same tick would restore what the first removed.
      for (const key of ['q', 'category', 'open', 'install', 'plan']) next.delete(key)
      return next
    }, { replace: true })
  }

  const cardProps = (deployment: Deployment): DeploymentCardProps => ({
    deployment,
    userId: user!.id,
    deletePending: deletePendingIds.has(deployment.id),
    onEdit: setEditDeployment,
    onDelete: setDeleteTarget,
  })

  const claimPending =
    !subdomainQuery.isLoading && !holdsSubdomain && Boolean(platformDomain) && Boolean(user)

  // Not a peer of a deployment card: a task, spanning the row, with its content
  // centred on the domain name it is asking for.
  const claimCard =
    claimPending && !invitationDismissed ? (
      <Grid size={{ xs: 12 }}>
        <Card sx={{ px: 3.5, py: 5 }}>
          <ClaimSubdomain
            domain={platformDomain}
            email={user!.email}
            context="account"
            autoSelect
            onDismiss={() => setInvitationDismissed(true)}
          />
        </Card>
      </Grid>
    ) : null

  return (
    <Stack spacing={4}>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        alignItems={{ xs: 'flex-start', sm: 'flex-end' }}
        justifyContent="space-between"
        spacing={2}
      >
        <PageHeading eyebrow="Your pod" title="Your apps" subtitle="The apps you run, and everything about them." />
        {!showEmpty && (
          <Button variant="contained" startIcon={<AddRounded />} onClick={() => openCatalog()} sx={{ flex: '0 0 auto' }}>
            Add an app
          </Button>
        )}
      </Stack>

      {claimPending && invitationDismissed && (
        <ClaimSubdomainBanner onChoose={() => setInvitationDismissed(false)} />
      )}

      {claimCard && <Grid container spacing={2}>{claimCard}</Grid>}

      {showEmpty && <StarterApps onPick={openCatalog} onBrowse={() => openCatalog()} />}

      {!showEmpty && deployments.length > 0 && (
        <DeploymentToolbar
          search={filter.search}
          onSearch={filter.setSearch}
          sort={filter.sort}
          onSort={filter.setSort}
          shown={shown.length}
          total={deployments.length}
          slashShortcut={!drawerOpen}
        />
      )}

      {!showEmpty && filter.search && shown.length === 0 && (
        <Typography sx={{ py: 6, textAlign: 'center', color: 'text.secondary' }}>
          None of your apps match “{filter.search}”.
        </Typography>
      )}

      {!showEmpty && (
        <Box sx={{ borderTop: '1px solid rgba(148, 163, 184, 0.14)' }}>
          {shown.map((deployment) => <DeploymentRow key={deployment.id} {...cardProps(deployment)} />)}
          <AddAppRow onClick={() => openCatalog()} />
        </Box>
      )}


      <AddAppDrawer open={drawerOpen} onClose={closeCatalog} />

      {editDeployment && user && editDeployment.desired_template?.product && (
        <DeployDialog
          product={editDeployment.desired_template.product}
          userId={user.id}
          deployment={editDeployment}
          onClose={() => setEditDeployment(null)}
        />
      )}

      {deleteTarget && (
        <ConfirmDeleteDialog
          name={deleteTarget.desired_template?.product?.name ?? 'this deployment'}
          subject="deployment"
          confirmValue={deleteTarget.hostname ?? deleteTarget.id}
          onConfirm={() => {
            deleteDeploymentMutation.mutate(deleteTarget.id)
            setDeleteTarget(null)
          }}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </Stack>
  )
}

export default Dashboard
