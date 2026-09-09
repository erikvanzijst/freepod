import {
  Box,
  Card,
  Grid,
  Stack,
  Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import {
  deleteDeployment,
  listDeployments,
  listProducts,
} from '../api/endpoints'
import type { Deployment, Product } from '../api/types'
import { useAuth } from '../state/AuthContext'
import { isTransitionalStatus } from '../utils/deploymentStatus'
import { ProductList } from '../components/ProductList'
import { DeployDialog } from '../components/DeployDialog'
import { ConfirmDeleteDialog } from '../components/ConfirmDeleteDialog'
import { DeploymentCard } from '../components/DeploymentCard'
import { PageHeading } from '../components/PageHeading'
import { ClaimSubdomain } from '../components/subdomain/ClaimSubdomain'
import { ClaimSubdomainBanner } from '../components/subdomain/ClaimSubdomainBanner'
import { ClaimSubdomainDialog } from '../components/subdomain/ClaimSubdomainDialog'
import { useMySubdomain } from '../components/subdomain/useMySubdomain'

function Dashboard() {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const [deletePendingIds, setDeletePendingIds] = useState<Set<string>>(new Set())
  const [deployProduct, setDeployProduct] = useState<Product | null>(null)
  const [editDeployment, setEditDeployment] = useState<Deployment | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Deployment | null>(null)
  const [claimOpen, setClaimOpen] = useState(false)
  // Session state only: dismissing is not an answer, so it is not recorded
  // anywhere and the invitation returns on reload.
  const [invitationDismissed, setInvitationDismissed] = useState(false)
  // The deploy the claim interrupted, resumed once a domain name is held.
  const [pendingDeploy, setPendingDeploy] = useState<Product | null>(null)

  const subdomainQuery = useMySubdomain()
  const holdsSubdomain = Boolean(subdomainQuery.data?.subdomain)
  const platformDomain = subdomainQuery.data?.domain ?? ''

  const productsQuery = useQuery({
    queryKey: ['products'],
    queryFn: () => listProducts(),
    enabled: Boolean(user),
  })

  const deployableProducts = useMemo<Product[]>(() => {
    return (productsQuery.data ?? []).filter((product) => Boolean(product.template_id))
  }, [productsQuery.data])

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

  const openDeploy = (product: Product) => {
    // The claim gates opening the deploy dialog rather than sitting inside it,
    // so no half-filled form is ever thrown away to ask for a domain name.
    if (!holdsSubdomain) {
      setPendingDeploy(product)
      setClaimOpen(true)
      return
    }
    setDeployProduct(product)
  }

  const claimDialog = platformDomain && user ? (
    <ClaimSubdomainDialog
      open={claimOpen}
      domain={platformDomain}
      email={user.email}
      onClose={() => {
        setClaimOpen(false)
        setPendingDeploy(null)
      }}
      onClaimed={() => {
        if (pendingDeploy) setDeployProduct(pendingDeploy)
        setPendingDeploy(null)
      }}
    />
  ) : null

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
      <PageHeading
        eyebrow="Your space"
        title="Your applications"
        subtitle="Spin up new products and keep track of your live environments."
      />

      {claimPending && invitationDismissed && (
        <ClaimSubdomainBanner onChoose={() => setInvitationDismissed(false)} />
      )}

      <Grid container spacing={2}>
        {claimCard}
        {deploymentsQuery.data
          ?.map((deployment) => (
          <Grid size={{ xs: 12, md: 6 }} key={deployment.id}>
            <DeploymentCard
              deployment={deployment}
              userId={user!.id}
              deletePending={deletePendingIds.has(deployment.id)}
              onEdit={setEditDeployment}
              onDelete={setDeleteTarget}
            />
          </Grid>
        ))}
        {!deploymentsQuery.isLoading &&
          (deploymentsQuery.data?.length ?? 0) === 0 && (
          <Grid size={{ xs: 12 }}>
            <Card sx={{ p: 4 }}>
              <Stack spacing={1}>
                <Typography variant="h6">No applications yet</Typography>
                <Typography color="text.secondary">
                  Choose an application below to launch your first instance.
                </Typography>
              </Stack>
            </Card>
          </Grid>
        )}
      </Grid>

      <Box>
        <Typography variant="h5">Available applications</Typography>
        <Typography color="text.secondary" sx={{ mb: 2 }}>
          Click an app to launch your own instance.
        </Typography>
        <ProductList
          products={deployableProducts}
          selectedProductId={null}
          onSelectProduct={(id) => {
            const product = deployableProducts.find((p) => p.id === id)
            if (product) openDeploy(product)
          }}
        />
      </Box>

      {claimDialog}

      {deployProduct && user && (
        <DeployDialog
          product={deployProduct}
          userId={user.id}
          onClose={() => setDeployProduct(null)}
        />
      )}

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
