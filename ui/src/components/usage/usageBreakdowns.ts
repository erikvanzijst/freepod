import type { Product, UsageReport } from '../../api/types'
import type { UsageBreakdownOption } from './UsageExplorer'
import { columnLabels } from './usageModel'

const METRIC_LABELS: Record<string, string> = {
  cpu_core_hours: 'CPU',
  ram_byte_hours: 'Memory',
}

/** A deployment's hostname, else its name, as the report carries them. */
export function deploymentLabeler(report: UsageReport) {
  const labels = columnLabels(report, 'deployment_id', ['deployment_hostname', 'deployment_name'])
  return (id: string) => labels.get(id) ?? id
}

export const byResource: UsageBreakdownOption = {
  dimension: 'metric',
  label: 'By resource',
  heading: 'Resource',
  keyColumn: 'metric',
  labeler: () => (key) => METRIC_LABELS[key] ?? key,
  order: () => Object.keys(METRIC_LABELS),
}

export const byApplication: UsageBreakdownOption = {
  dimension: 'deployment',
  label: 'By application',
  heading: 'Application',
  keyColumn: 'deployment_id',
  labeler: deploymentLabeler,
}

/**
 * The catalog is small and changes rarely, so a product keeps one color: ranked
 * by id, with products the catalog no longer lists after it.
 */
export function byProduct(catalog: Product[]): UsageBreakdownOption {
  const order = [...catalog].sort((a, b) => a.id - b.id).map((p) => String(p.id))
  return {
    dimension: 'product',
    label: 'By product',
    heading: 'Product',
    keyColumn: 'product_id',
    labeler: (report) => {
      const labels = columnLabels(report, 'product_id', ['product_name'])
      return (id) => labels.get(id) ?? `Product ${id}`
    },
    order: () => order,
  }
}
