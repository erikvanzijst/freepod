import { Autocomplete, TextField } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { getAllUsage, getAllUsageCsv, listDeployments, listProducts, listUsers } from '../api/endpoints'
import type { UsageDimension } from '../api/types'
import { UsageExplorer, type UsageBreakdownOption } from './usage/UsageExplorer'
import { byApplication, byProduct, byResource } from './usage/usageBreakdowns'

/**
 * What the platform's tenants cost, split only by what stays small as the
 * customer base grows: product and resource. One account or deployment is a
 * filter, never a dimension. Deeper analysis belongs in a tool pointed at the
 * ledger itself, not in more endpoints.
 */
export function AdminUsagePanel() {
  const [params, setParams] = useSearchParams()
  const rawUser = params.get('user')
  const userId = rawUser && /^\d+$/.test(rawUser) ? Number(rawUser) : undefined
  const deploymentId = (userId != null && params.get('deployment')) || undefined

  // Shares the Users pane's cache entry: one fetch of the full list serves both.
  const usersQuery = useQuery({ queryKey: ['admin-users'], queryFn: listUsers })
  const productsQuery = useQuery({ queryKey: ['products'], queryFn: listProducts })
  const deploymentsQuery = useQuery({
    queryKey: ['deployments', userId],
    queryFn: () => listDeployments(userId!),
    enabled: userId != null,
  })

  const users = [...(usersQuery.data ?? [])].sort((a, b) => a.email.localeCompare(b.email))
  const deployments = [...(deploymentsQuery.data ?? [])].sort((a, b) =>
    (a.hostname ?? a.name).localeCompare(b.hostname ?? b.name),
  )
  const selectedUser = users.find((u) => u.id === userId) ?? null
  const selectedDeployment = deployments.find((d) => d.id === deploymentId) ?? null

  const setFilter = (key: 'user' | 'deployment', value: string | undefined) =>
    setParams(
      (current) => {
        const updated = new URLSearchParams(current)
        if (value == null) updated.delete(key)
        else updated.set(key, value)
        // A deployment belongs to one account; changing account drops it.
        if (key === 'user') updated.delete('deployment')
        return updated
      },
      { replace: true },
    )

  const product = byProduct(productsQuery.data ?? [])
  const breakdowns: UsageBreakdownOption[] = deploymentId
    ? [byResource]
    : userId != null
      ? [byApplication, product, byResource]
      : [product, byResource]
  const csvGroupBy: UsageDimension[] =
    userId != null ? ['deployment', 'product', 'metric'] : ['product', 'metric']

  return (
    <UsageExplorer
      title="Usage"
      description="Billable CPU and memory across every account, priced at the rate in effect for each hour. Platform services are not included. Times are UTC; amounts exclude VAT."
      scope={['all', userId ?? null, deploymentId ?? null]}
      enabled
      fetchReport={(query) => getAllUsage({ ...query, deploymentId }, userId)}
      fetchCsv={(query) => getAllUsageCsv({ ...query, deploymentId }, userId)}
      csvGroupBy={csvGroupBy}
      csvName={
        deploymentId
          ? `freepod-usage-deployment-${deploymentId}`
          : userId != null
            ? `freepod-usage-user-${userId}`
            : 'freepod-usage-all'
      }
      breakdowns={breakdowns}
      filters={
        <>
          <Autocomplete
            size="small"
            sx={{ width: 240 }}
            options={users}
            value={selectedUser}
            loading={usersQuery.isLoading}
            getOptionLabel={(u) => u.email}
            isOptionEqualToValue={(a, b) => a.id === b.id}
            onChange={(_, u) => setFilter('user', u ? String(u.id) : undefined)}
            renderInput={(props) => <TextField {...props} placeholder="All users" />}
          />
          {userId != null && (
            <Autocomplete
              size="small"
              sx={{ width: 240 }}
              options={deployments}
              value={selectedDeployment}
              loading={deploymentsQuery.isLoading}
              getOptionLabel={(d) => d.hostname ?? d.name}
              isOptionEqualToValue={(a, b) => a.id === b.id}
              onChange={(_, d) => setFilter('deployment', d?.id)}
              renderInput={(props) => <TextField {...props} placeholder="All applications" />}
            />
          )}
        </>
      }
    />
  )
}

export default AdminUsagePanel
