import type { UsageBucket, UsageReport } from '../../api/types'

/**
 * Period math and report pivoting for the usage pane. Everything here is UTC:
 * the ledger's buckets are UTC, and labeling them in local time would put a
 * day's usage under the wrong date for anyone west of Greenwich.
 */

export type UsagePeriod = 'day' | 'week' | 'month' | 'year'

export interface PeriodRange {
  start: Date
  end: Date
  bucket: UsageBucket
  /** Every bucket start in the period, so empty buckets still take a slot. */
  slots: Date[]
}

const DAY_MS = 86_400_000

function utc(year: number, month: number, day = 1, hour = 0) {
  return new Date(Date.UTC(year, month, day, hour))
}

/** The period of the given kind containing `anchor`. Weeks start on Monday. */
export function periodRange(period: UsagePeriod, anchor: Date): PeriodRange {
  const y = anchor.getUTCFullYear()
  const m = anchor.getUTCMonth()
  const d = anchor.getUTCDate()
  switch (period) {
    case 'day': {
      const start = utc(y, m, d)
      return {
        start,
        end: utc(y, m, d + 1),
        bucket: 'hour',
        slots: Array.from({ length: 24 }, (_, h) => utc(y, m, d, h)),
      }
    }
    case 'week': {
      const sinceMonday = (anchor.getUTCDay() + 6) % 7
      const start = utc(y, m, d - sinceMonday)
      return {
        start,
        end: new Date(start.getTime() + 7 * DAY_MS),
        bucket: 'day',
        slots: Array.from({ length: 7 }, (_, i) => new Date(start.getTime() + i * DAY_MS)),
      }
    }
    case 'month': {
      const end = utc(y, m + 1)
      const days = new Date(end.getTime() - DAY_MS).getUTCDate()
      return {
        start: utc(y, m),
        end,
        bucket: 'day',
        slots: Array.from({ length: days }, (_, i) => utc(y, m, i + 1)),
      }
    }
    case 'year':
      return {
        start: utc(y, 0),
        end: utc(y + 1, 0),
        bucket: 'month',
        slots: Array.from({ length: 12 }, (_, i) => utc(y, i)),
      }
  }
}

/** An anchor inside the period before (`-1`) or after (`1`) the current one. */
export function shiftAnchor(period: UsagePeriod, anchor: Date, step: -1 | 1): Date {
  const { start, end } = periodRange(period, anchor)
  return step < 0 ? new Date(start.getTime() - 1) : end
}

/** A bar's period when clicked, if there is a finer one to drill into. */
export function drillDown(period: UsagePeriod): UsagePeriod | null {
  if (period === 'year') return 'month'
  if (period === 'week' || period === 'month') return 'day'
  return null
}

function fmt(date: Date, options: Intl.DateTimeFormatOptions) {
  return date.toLocaleString(undefined, { timeZone: 'UTC', ...options })
}

/** A short axis label for one slot. */
export function slotLabel(period: UsagePeriod, slot: Date): string {
  switch (period) {
    case 'day':
      return fmt(slot, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
    case 'week':
      return fmt(slot, { weekday: 'short', day: 'numeric' })
    case 'month':
      return fmt(slot, { day: 'numeric' })
    case 'year':
      return fmt(slot, { month: 'short' })
  }
}

/** The full name of one slot, for tooltips. */
export function slotTitle(period: UsagePeriod, slot: Date): string {
  if (period === 'day') {
    const end = new Date(slot.getTime() + 3_600_000)
    const hm: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }
    return `${fmt(slot, { weekday: 'short', month: 'short', day: 'numeric', ...hm })}–${fmt(end, hm)} UTC`
  }
  if (period === 'year') return fmt(slot, { month: 'long', year: 'numeric' })
  return fmt(slot, { weekday: 'long', month: 'long', day: 'numeric' })
}

/** The heading for a whole period. */
export function periodTitle(period: UsagePeriod, range: PeriodRange): string {
  switch (period) {
    case 'day':
      return fmt(range.start, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
    case 'week': {
      const last = new Date(range.end.getTime() - DAY_MS)
      return `${fmt(range.start, { month: 'short', day: 'numeric' })} – ${fmt(last, { month: 'short', day: 'numeric', year: 'numeric' })}`
    }
    case 'month':
      return fmt(range.start, { month: 'long', year: 'numeric' })
    case 'year':
      return fmt(range.start, { year: 'numeric' })
  }
}

/** The API's naive-UTC timestamps, as instants. */
export function parseUtc(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)
}

export interface UsageSeries {
  key: string
  data: (number | null)[]
  total: number
}

/**
 * Pivot a report grouped by one dimension into one series per value of it,
 * aligned to `slots`. A bucket the ledger has nothing for stays `null`, not 0.
 */
export function pivot(report: UsageReport, keyColumn: string, slots: Date[]): UsageSeries[] {
  const keyAt = report.columns.indexOf(keyColumn)
  const costAt = report.columns.indexOf('cost')
  const slotAt = new Map(slots.map((slot, i) => [slot.getTime(), i]))
  const series = new Map<string, UsageSeries>()

  for (const row of report.rows) {
    const index = slotAt.get(parseUtc(row[0] as string).getTime())
    const raw = row[keyAt]
    if (index === undefined || raw == null) continue
    const key = String(raw)
    let entry = series.get(key)
    if (!entry) {
      entry = { key, data: slots.map(() => null), total: 0 }
      series.set(key, entry)
    }
    const cost = Number(row[costAt] ?? 0)
    entry.data[index] = (entry.data[index] ?? 0) + cost
    entry.total += cost
  }
  return [...series.values()]
}

/**
 * Labels for each value of `keyColumn`, read off the report itself: the first
 * non-null of `labelColumns`, e.g. a deployment's hostname, else its name.
 */
export function columnLabels(
  report: UsageReport,
  keyColumn: string,
  labelColumns: string[],
): Map<string, string> {
  const keyAt = report.columns.indexOf(keyColumn)
  const labelAts = labelColumns.map((c) => report.columns.indexOf(c)).filter((i) => i >= 0)
  const labels = new Map<string, string>()
  if (keyAt < 0) return labels
  for (const row of report.rows) {
    const label = labelAts.map((i) => row[i]).find((v) => v != null)
    if (row[keyAt] != null && label != null) labels.set(String(row[keyAt]), String(label))
  }
  return labels
}

/**
 * Euros at a precision that keeps small amounts legible: a single hour of a
 * small app costs a fraction of a cent, which "€0.00" would hide.
 */
export function formatEuro(amount: number, currency = 'EUR'): string {
  const abs = Math.abs(amount)
  const digits = abs === 0 || abs >= 1 ? 2 : abs >= 0.01 ? 3 : 4
  return amount.toLocaleString(undefined, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: digits,
  })
}
