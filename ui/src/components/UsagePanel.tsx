import { useQuery } from '@tanstack/react-query'
import { getUsage, getUsageCsv, listDeployments } from '../api/endpoints'
import { useAuth } from '../state/AuthContext'
import { UsageExplorer, type UsageBreakdownOption } from './usage/UsageExplorer'
import { byResource, deploymentLabeler } from './usage/usageBreakdowns'

/**
 * What the account's deployments cost, per period. Figures are estimates from
 * the usage ledger, priced at the rate in effect for each hour.
 */
export function UsagePanel() {
  const { user } = useAuth()
  const deploymentsQuery = useQuery({
    queryKey: ['deployments', user?.id],
    queryFn: () => listDeployments(user!.id),
    enabled: Boolean(user?.id),
  })

  // Oldest first: a deployment keeps its color for as long as it exists.
  const deployments = [...(deploymentsQuery.data ?? [])].sort((a, b) =>
    a.created_at.localeCompare(b.created_at),
  )
  const hostnames = new Map(deployments.map((d) => [d.id, d.hostname ?? d.name]))
  const breakdowns: UsageBreakdownOption[] = [
    {
      dimension: 'deployment',
      label: 'By application',
      heading: 'Application',
      keyColumn: 'deployment_id',
      labeler: (report) => {
        const fromReport = deploymentLabeler(report)
        return (id) => hostnames.get(id) ?? `${fromReport(id)} (deleted)`
      },
      order: () => deployments.map((d) => d.id),
    },
    byResource,
  ]

  return (
    <UsageExplorer
      title="Usage"
      description="The CPU and memory your applications used, and what it costs. Measured hourly; times are UTC and amounts exclude VAT."
      scope={['user', user?.id]}
      enabled={Boolean(user?.id)}
      fetchReport={(query) => getUsage(user!.id, query)}
      fetchCsv={(query) => getUsageCsv(user!.id, query)}
      csvGroupBy={['deployment', 'metric']}
      csvName="freepod-usage"
      breakdowns={breakdowns}
    />
  )
}

export default UsagePanel
