import { useMemo, useState, type ReactNode } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CircularProgress,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import FileDownloadOutlinedIcon from '@mui/icons-material/FileDownloadOutlined'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import type { UsageDimension, UsageQuery, UsageReport } from '../../api/types'
import { fg, MONO } from '../landing/landingTokens'
import { UsageBreakdown } from './UsageBreakdown'
import { UsageChart } from './UsageChart'
import { UsagePeriodControls } from './UsagePeriodControls'
import { colorSeries, OTHER_COLOR, type ColoredSeries } from './usagePalette'
import {
  drillDown,
  formatEuro,
  parseUtc,
  periodRange,
  pivot,
  type UsagePeriod,
  type UsageSeries,
} from './usageModel'

/** One way to split the bars: by user, by application or by resource. */
export interface UsageBreakdownOption {
  dimension: UsageDimension
  /** The toggle's text, e.g. "By application". */
  label: string
  /** The breakdown table's first column heading. */
  heading: string
  /** The report column that identifies a series. */
  keyColumn: string
  /** A series' name, given the report it came from. */
  labeler: (report: UsageReport) => (key: string) => string
  /**
   * The ranking that fixes each series' color. Defaults to heaviest first,
   * which is what "who uses the most" wants; a stable ranking suits a small,
   * known set better, since then a series keeps its color across periods.
   */
  order?: (series: UsageSeries[]) => string[]
}

interface UsageExplorerProps {
  title: string
  description: ReactNode
  /** Distinguishes this explorer's cached reports from another's. */
  scope: unknown[]
  enabled: boolean
  fetchReport: (query: UsageQuery) => Promise<UsageReport>
  fetchCsv: (query: UsageQuery) => Promise<Blob>
  /** The export's grouping: finer than the chart's, for spreadsheet pivoting. */
  csvGroupBy: UsageDimension[]
  csvName: string
  breakdowns: UsageBreakdownOption[]
  /** Controls that narrow what is shown, beside the period controls. */
  filters?: ReactNode
}

const PERIODS: UsagePeriod[] = ['day', 'week', 'month', 'year']

const heaviestFirst = (series: UsageSeries[]) =>
  [...series].sort((a, b) => b.total - a.total).map((s) => s.key)

/**
 * Period and anchor live in the URL, so a view survives a reload and can be
 * linked. Other parameters, such as a page's own filters, are left alone.
 */
function usePeriodParams(now: Date) {
  const [params, setParams] = useSearchParams()
  const rawPeriod = params.get('period') as UsagePeriod | null
  const period = rawPeriod && PERIODS.includes(rawPeriod) ? rawPeriod : 'month'
  const at = params.get('at')
  const parsed = at ? new Date(`${at}T00:00:00Z`) : null
  const anchor = parsed && !Number.isNaN(parsed.getTime()) ? parsed : now
  const set = (next: UsagePeriod, nextAnchor: Date) => {
    const start = periodRange(next, nextAnchor).start
    setParams(
      (current) => {
        const updated = new URLSearchParams(current)
        updated.set('period', next)
        updated.set('at', start.toISOString().slice(0, 10))
        return updated
      },
      { replace: true },
    )
  }
  return { period, anchor, set }
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

/** Cost per period as stacked bars, a total and a breakdown table, with CSV export. */
export function UsageExplorer({
  title,
  description,
  scope,
  enabled,
  fetchReport,
  fetchCsv,
  csvGroupBy,
  csvName,
  breakdowns,
  filters,
}: UsageExplorerProps) {
  const [now] = useState(() => new Date())
  const { period, anchor, set } = usePeriodParams(now)
  const [dimension, setDimension] = useState<UsageDimension>(breakdowns[0].dimension)
  const [downloading, setDownloading] = useState(false)
  const breakdown = breakdowns.find((b) => b.dimension === dimension) ?? breakdowns[0]

  const range = periodRange(period, anchor)
  const query: UsageQuery = {
    start: range.start,
    end: range.end,
    bucket: range.bucket,
    groupBy: [breakdown.dimension],
  }

  const usageQuery = useQuery({
    queryKey: ['usage', ...scope, range.start.toISOString(), period, breakdown.dimension],
    queryFn: () => fetchReport(query),
    enabled,
    placeholderData: keepPreviousData,
  })

  const report = usageQuery.data
  // The chart folds what does not fit into "Other"; the table lists everyone.
  const { series, rows } = useMemo(() => {
    if (!report) return { series: [], rows: [] }
    const pivoted = pivot(report, breakdown.keyColumn, range.slots)
    const label = breakdown.labeler(report)
    const colored = colorSeries(pivoted, (breakdown.order ?? heaviestFirst)(pivoted), label)
    const colorOf = new Map(colored.map((s) => [s.key, s.color]))
    const rows: ColoredSeries[] = pivoted.map((s) => ({
      ...s,
      label: label(s.key),
      color: colorOf.get(s.key) ?? OTHER_COLOR,
    }))
    return { series: colored, rows }
    // range.slots is derived from period and anchor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report, breakdown, period, anchor.getTime()])

  const currency = report?.currency ?? 'EUR'
  const total = series.reduce((sum, s) => sum + s.total, 0)
  const through = report?.recorded_through ? parseUtc(report.recorded_through) : null
  const inProgress = range.start <= now && now < range.end
  const finer = drillDown(period)

  const download = async () => {
    setDownloading(true)
    try {
      const blob = await fetchCsv({ ...query, groupBy: csvGroupBy })
      saveBlob(blob, `${csvName}-${range.start.toISOString().slice(0, 10)}-${period}.csv`)
    } finally {
      setDownloading(false)
    }
  }

  return (
    <Card sx={{ p: { xs: 2.5, sm: 3 } }}>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        alignItems={{ xs: 'flex-start', sm: 'center' }}
        sx={{ mb: 2 }}
      >
        <Box sx={{ flex: 1 }}>
          <Typography variant="h6">{title}</Typography>
          <Typography color="text.secondary" variant="body2" sx={{ mt: 0.5 }}>
            {description}
          </Typography>
        </Box>
        <Button
          variant="outlined"
          size="small"
          startIcon={<FileDownloadOutlinedIcon />}
          onClick={download}
          disabled={!enabled || downloading}
          sx={{ flexShrink: 0 }}
        >
          Export CSV
        </Button>
      </Stack>

      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={1.5}
        justifyContent="space-between"
        alignItems={{ xs: 'flex-start', md: 'center' }}
        useFlexGap
        flexWrap="wrap"
        sx={{ mb: 2 }}
      >
        <UsagePeriodControls period={period} anchor={anchor} now={now} onChange={set} />
        <Stack direction="row" spacing={1.5} alignItems="center" useFlexGap flexWrap="wrap">
          {filters}
          {breakdowns.length > 1 && (
            <ToggleButtonGroup
              size="small"
              exclusive
              value={breakdown.dimension}
              onChange={(_, value: UsageDimension | null) => value && setDimension(value)}
              aria-label="Break down by"
            >
              {breakdowns.map((b) => (
                <ToggleButton key={b.dimension} value={b.dimension} sx={{ px: 1.5 }}>
                  {b.label}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
          )}
        </Stack>
      </Stack>

      <Stack direction="row" alignItems="baseline" spacing={1.5} sx={{ mb: 1 }}>
        <Typography sx={{ fontSize: 32, fontWeight: 600, letterSpacing: '-0.02em' }}>
          {report ? formatEuro(total, currency) : '–'}
        </Typography>
        {inProgress && through && (
          <Typography sx={{ color: fg.muted, fontFamily: MONO, fontSize: 12 }}>
            so far · measured through{' '}
            {through.toLocaleString(undefined, {
              timeZone: 'UTC',
              month: 'short',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
              hourCycle: 'h23',
            })}{' '}
            UTC
          </Typography>
        )}
      </Stack>

      {usageQuery.error != null && (
        <Alert severity="error" variant="outlined" sx={{ my: 2 }}>
          Could not load usage: {(usageQuery.error as Error).message}
        </Alert>
      )}

      {usageQuery.isLoading && (
        <Stack alignItems="center" sx={{ py: 10 }}>
          <CircularProgress size={22} />
        </Stack>
      )}

      {report && (
        <Box sx={{ opacity: usageQuery.isPlaceholderData ? 0.5 : 1, transition: 'opacity 0.2s' }}>
          {series.length === 0 ? (
            <Typography color="text.secondary" sx={{ py: 8, textAlign: 'center' }}>
              No usage recorded for this {period}.
            </Typography>
          ) : (
            <>
              <UsageChart
                period={period}
                slots={range.slots}
                series={series}
                currency={currency}
                onBucketClick={finer ? (i) => set(finer, range.slots[i]) : undefined}
              />
              <Box sx={{ mt: 2 }}>
                <UsageBreakdown series={rows} heading={breakdown.heading} currency={currency} />
              </Box>
            </>
          )}
        </Box>
      )}
    </Card>
  )
}
