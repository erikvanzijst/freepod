import { BarChart } from '@mui/x-charts/BarChart'
import { fg, ink, line, MONO } from '../landing/landingTokens'
import type { ColoredSeries } from './usagePalette'
import { formatEuro, slotLabel, slotTitle, type UsagePeriod } from './usageModel'

interface UsageChartProps {
  period: UsagePeriod
  slots: Date[]
  series: ColoredSeries[]
  currency: string
  /** Called with the clicked bucket's index, when drilling down is possible. */
  onBucketClick?: (index: number) => void
}

/** Cost per bucket, one stacked segment per series. */
export function UsageChart({ period, slots, series, currency, onBucketClick }: UsageChartProps) {
  return (
    <BarChart
      height={320}
      borderRadius={4}
      grid={{ horizontal: true }}
      margin={{ left: 8, right: 8 }}
      xAxis={[
        {
          scaleType: 'band',
          data: slots,
          categoryGapRatio: 0.35,
          valueFormatter: (slot: Date, context) =>
            context.location === 'tooltip' ? slotTitle(period, slot) : slotLabel(period, slot),
          tickLabelStyle: { fill: fg.muted, fontSize: 11, fontFamily: MONO },
          disableLine: true,
          disableTicks: true,
        },
      ]}
      yAxis={[
        {
          width: 64,
          valueFormatter: (value: number) => formatEuro(value, currency),
          tickLabelStyle: { fill: fg.muted, fontSize: 11, fontFamily: MONO },
          disableLine: true,
          disableTicks: true,
        },
      ]}
      series={series.map((s) => ({
        id: s.key,
        label: s.label,
        data: s.data,
        color: s.color,
        stack: 'total',
        valueFormatter: (value: number | null) =>
          value == null ? null : formatEuro(value, currency),
      }))}
      onAxisClick={onBucketClick ? (_, data) => data && onBucketClick(data.dataIndex) : undefined}
      slotProps={{
        legend: {
          toggleVisibilityOnClick: true,
          sx: { color: fg.primary, fontSize: 13 },
        },
        tooltip: { trigger: 'axis' },
      }}
      sx={{
        // A surface-colored seam between stacked segments.
        '& .MuiBarElement-root': { stroke: ink.base, strokeWidth: 2 },
        '& .MuiChartsGrid-line': { stroke: line.soft },
        cursor: onBucketClick ? 'pointer' : undefined,
      }}
    />
  )
}
