import { describe, expect, it } from 'vitest'
import type { UsageReport } from '../../api/types'
import { byResource } from './usageBreakdowns'
import type { UsageSeries } from './usageModel'
import { CATEGORICAL, colorSeries } from './usagePalette'

const series = (key: string): UsageSeries => ({ key, data: [1], total: 1 })

describe('byResource', () => {
  const label = byResource.labeler({} as UsageReport)
  const order = byResource.order!([])

  it('names storage "Database" and "Object storage" beside CPU and Memory', () => {
    expect(
      ['cpu_core_hours', 'ram_byte_hours', 'db_byte_hours', 'object_storage_byte_hours'].map(
        label,
      ),
    ).toEqual(['CPU', 'Memory', 'Database', 'Object storage'])
  })

  it('keeps Database in the third color whichever resources a period has', () => {
    const colored = colorSeries([series('db_byte_hours'), series('cpu_core_hours')], order, label)
    expect(colored.map((s) => [s.label, s.color])).toEqual([
      ['CPU', CATEGORICAL[0]],
      ['Database', CATEGORICAL[2]],
    ])
  })

  it('keeps Object storage in the fourth color whichever resources a period has', () => {
    const colored = colorSeries(
      [series('object_storage_byte_hours'), series('ram_byte_hours')],
      order,
      label,
    )
    expect(colored.map((s) => [s.label, s.color])).toEqual([
      ['Memory', CATEGORICAL[1]],
      ['Object storage', CATEGORICAL[3]],
    ])
  })
})
