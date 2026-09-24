import { useMemo, useState } from 'react'
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
import { getUsage, getUsageCsv, listDeployments } from '../api/endpoints'
import type { UsageDimension, UsageQuery } from '../api/types'
import { useAuth } from '../state/AuthContext'
import { fg, MONO } from './landing/landingTokens'
import { UsageBreakdown } from './usage/UsageBreakdown'
import { UsageChart } from './usage/UsageChart'
import { UsagePeriodControls } from './usage/UsagePeriodControls'
import { colorSeries } from './usage/usagePalette'
import {
  deploymentNames,
  drillDown,
  formatEuro,
  parseUtc,
  periodRange,
  pivot,
  type UsagePeriod,
} from './usage/usageModel'

const METRIC_LABELS: Record<string, string> = {
  cpu_core_hours: 'CPU',
  ram_byte_hours: 'Memory',
}
const METRIC_ORDER = Object.keys(METRIC_LABELS)
const PERIODS: UsagePeriod[] = ['day', 'week', 'month', 'year']

/** Period and anchor live in the URL, so a view survives a reload and can be linked. */
function usePeriodParams(now: Date) {
  const [params, setParams] = useSearchParams()
  const rawPeriod = params.get('period') as UsagePeriod | null
  const period = rawPeriod && PERIODS.includes(rawPeriod) ? rawPeriod : 'month'
  const at = params.get('at')
  const parsed = at ? new Date(`${at}T00:00:00Z`) : null
  const anchor = parsed && !Number.isNaN(parsed.getTime()) ? parsed : now
  const set = (next: UsagePeriod, nextAnchor: Date) => {
    const start = periodRange(next, nextAnchor).start
    setParams({ period: next, at: start.toISOString().slice(0, 10) }, { replace: true })
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

/**
 * What the account's deployments cost, per period. Figures are estimates from
 * the usage ledger, priced at the rate in effect for each hour.
 */
export function UsagePanel() {
  const { user } = useAuth()
  const [now] = useState(() => new Date())
  const { period, anchor, set } = usePeriodParams(now)
  const [colorBy, setColorBy] = useState<UsageDimension>('deployment')
  const [downloading, setDownloading] = useState(false)

  const range = periodRange(period, anchor)
  const query: UsageQuery = {
    start: range.start,
    end: range.end,
    bucket: range.bucket,
    groupBy: [colorBy],
  }

  const usageQuery = useQuery({
    queryKey: ['usage', user?.id, range.start.toISOString(), period, colorBy],
    queryFn: () => getUsage(user!.id, query),
    enabled: Boolean(user?.id),
    placeholderData: keepPreviousData,
  })
  const deploymentsQuery = useQuery({
    queryKey: ['deployments', user?.id],
    queryFn: () => listDeployments(user!.id),
    enabled: Boolean(user?.id),
  })

  const report = usageQuery.data
  const series = useMemo(() => {
    if (!report) return []
    if (colorBy === 'metric') {
      return colorSeries(pivot(report, 'metric', range.slots), METRIC_ORDER, (key) => METRIC_LABELS[key] ?? key)
    }
    const deployments = [...(deploymentsQuery.data ?? [])].sort((a, b) =>
      a.created_at.localeCompare(b.created_at),
    )
    const hostnames = new Map(deployments.map((d) => [d.id, d.hostname ?? d.name]))
    const names = deploymentNames(report)
    return colorSeries(
      pivot(report, 'deployment_id', range.slots),
      deployments.map((d) => d.id),
      (id) => hostnames.get(id) ?? `${names.get(id) ?? id} (deleted)`,
    )
    // range.slots is derived from period and anchor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report, colorBy, deploymentsQuery.data, period, anchor.getTime()])

  const currency = report?.currency ?? 'EUR'
  const total = series.reduce((sum, s) => sum + s.total, 0)
  const through = report?.recorded_through ? parseUtc(report.recorded_through) : null
  const inProgress = range.start <= now && now < range.end
  const finer = drillDown(period)

  const download = async () => {
    setDownloading(true)
    try {
      const blob = await getUsageCsv(user!.id, { ...query, groupBy: ['deployment', 'metric'] })
      saveBlob(blob, `freepod-usage-${range.start.toISOString().slice(0, 10)}-${period}.csv`)
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
          <Typography variant="h6">Usage</Typography>
          <Typography color="text.secondary" variant="body2" sx={{ mt: 0.5 }}>
            The CPU and memory your applications used, and what it costs. Measured
            hourly; times are UTC and amounts exclude VAT.
          </Typography>
        </Box>
        <Button
          variant="outlined"
          size="small"
          startIcon={<FileDownloadOutlinedIcon />}
          onClick={download}
          disabled={!user || downloading}
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
        sx={{ mb: 2 }}
      >
        <UsagePeriodControls period={period} anchor={anchor} now={now} onChange={set} />
        <ToggleButtonGroup
          size="small"
          exclusive
          value={colorBy}
          onChange={(_, value: UsageDimension | null) => value && setColorBy(value)}
          aria-label="Break down by"
        >
          <ToggleButton value="deployment" sx={{ px: 1.5 }}>By application</ToggleButton>
          <ToggleButton value="metric" sx={{ px: 1.5 }}>By resource</ToggleButton>
        </ToggleButtonGroup>
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
          Could not load your usage: {(usageQuery.error as Error).message}
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
                <UsageBreakdown
                  series={series}
                  heading={colorBy === 'metric' ? 'Resource' : 'Application'}
                  currency={currency}
                />
              </Box>
            </>
          )}
        </Box>
      )}
    </Card>
  )
}

export default UsagePanel
