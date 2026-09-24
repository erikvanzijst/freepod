import { describe, expect, it } from 'vitest'
import type { UsageReport } from '../../api/types'
import { CATEGORICAL, colorSeries, OTHER_KEY } from './usagePalette'
import { parseUtc, periodRange, pivot, shiftAnchor } from './usageModel'

const at = (iso: string) => new Date(iso)

describe('periodRange', () => {
  it('starts a week on Monday, UTC', () => {
    const range = periodRange('week', at('2026-09-27T23:30:00Z')) // a Sunday
    expect(range.start.toISOString()).toBe('2026-09-21T00:00:00.000Z')
    expect(range.end.toISOString()).toBe('2026-09-28T00:00:00.000Z')
    expect(range.bucket).toBe('day')
    expect(range.slots).toHaveLength(7)
  })

  it('gives a month one slot per day', () => {
    expect(periodRange('month', at('2026-02-10T00:00:00Z')).slots).toHaveLength(28)
    expect(periodRange('month', at('2026-09-10T00:00:00Z')).slots).toHaveLength(30)
  })

  it('buckets a day by hour and a year by month', () => {
    expect(periodRange('day', at('2026-09-24T16:00:00Z')).bucket).toBe('hour')
    expect(periodRange('year', at('2026-09-24T16:00:00Z')).slots).toHaveLength(12)
  })
})

describe('shiftAnchor', () => {
  it('pages across a year boundary', () => {
    const previous = shiftAnchor('month', at('2026-01-15T00:00:00Z'), -1)
    expect(periodRange('month', previous).start.toISOString()).toBe('2025-12-01T00:00:00.000Z')
    const next = shiftAnchor('month', at('2025-12-15T00:00:00Z'), 1)
    expect(periodRange('month', next).start.toISOString()).toBe('2026-01-01T00:00:00.000Z')
  })
})

describe('parseUtc', () => {
  it('reads the API’s naive timestamps as UTC', () => {
    expect(parseUtc('2026-09-23T00:00:00').toISOString()).toBe('2026-09-23T00:00:00.000Z')
  })
})

const report = (rows: (string | null)[][]): UsageReport => ({
  user_id: 1,
  start: '2026-09-21T00:00:00',
  end: '2026-09-28T00:00:00',
  bucket: 'day',
  currency: 'EUR',
  recorded_through: null,
  columns: ['window_start', 'metric', 'unit', 'value', 'cost'],
  rows,
})

describe('pivot', () => {
  it('aligns series to slots and leaves unmeasured buckets null', () => {
    const { slots } = periodRange('week', at('2026-09-21T00:00:00Z'))
    const series = pivot(
      report([
        ['2026-09-23T00:00:00', 'cpu_core_hours', 'core_hours', '1', '0.5'],
        ['2026-09-24T00:00:00', 'cpu_core_hours', 'core_hours', '1', '0.25'],
        ['2026-09-24T00:00:00', 'ram_byte_hours', 'byte_hours', '9', '0.1'],
      ]),
      'metric',
      slots,
    )
    const cpu = series.find((s) => s.key === 'cpu_core_hours')!
    expect(cpu.data).toEqual([null, null, 0.5, 0.25, null, null, null])
    expect(cpu.total).toBe(0.75)
    expect(series.find((s) => s.key === 'ram_byte_hours')!.data[2]).toBeNull()
  })
})

describe('colorSeries', () => {
  const blank = (key: string) => ({ key, data: [1], total: 1 })

  it('colors by rank in the stable order, not by what is present', () => {
    const colored = colorSeries([blank('c'), blank('a')], ['a', 'b', 'c'], (k) => k)
    expect(colored.map((s) => [s.key, s.color])).toEqual([
      ['a', CATEGORICAL[0]],
      ['c', CATEGORICAL[2]],
    ])
  })

  it('folds what does not fit into Other', () => {
    const keys = Array.from({ length: 10 }, (_, i) => `k${i}`)
    const colored = colorSeries(keys.map(blank), keys, (k) => k)
    expect(colored).toHaveLength(CATEGORICAL.length)
    const other = colored[colored.length - 1]
    expect(other.key).toBe(OTHER_KEY)
    expect(other.total).toBe(3)
    expect(other.data).toEqual([3])
  })
})
