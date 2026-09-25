import { Box, Table, TableBody, TableCell, TableHead, TableRow } from '@mui/material'
import { fg } from '../landing/landingTokens'
import type { ColoredSeries } from './usagePalette'
import { formatEuro } from './usageModel'

interface UsageBreakdownProps {
  series: ColoredSeries[]
  heading: string
  currency: string
}

/** The period's totals per series: the chart's numbers, readable without it. */
export function UsageBreakdown({ series, heading, currency }: UsageBreakdownProps) {
  const total = series.reduce((sum, s) => sum + s.total, 0)
  const rows = [...series].sort((a, b) => b.total - a.total)
  return (
    <Table size="small" sx={{ '& td, & th': { borderColor: 'divider' } }}>
      <TableHead>
        <TableRow>
          <TableCell sx={{ color: fg.muted }}>{heading}</TableCell>
          <TableCell align="right" sx={{ color: fg.muted }}>Share</TableCell>
          <TableCell align="right" sx={{ color: fg.muted }}>Cost</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {rows.map((s) => (
          <TableRow key={s.key}>
            <TableCell>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25 }}>
                <Box sx={{ width: 10, height: 10, borderRadius: '3px', background: s.color, flexShrink: 0 }} />
                {s.label}
              </Box>
            </TableCell>
            <TableCell align="right" sx={{ color: fg.muted, fontVariantNumeric: 'tabular-nums' }}>
              {total > 0 ? `${((s.total / total) * 100).toFixed(0)}%` : '–'}
            </TableCell>
            <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
              {formatEuro(s.total, currency)}
            </TableCell>
          </TableRow>
        ))}
        <TableRow>
          <TableCell sx={{ fontWeight: 600, borderBottom: 0 }}>Total</TableCell>
          <TableCell sx={{ borderBottom: 0 }} />
          <TableCell align="right" sx={{ fontWeight: 600, borderBottom: 0, fontVariantNumeric: 'tabular-nums' }}>
            {formatEuro(total, currency)}
          </TableCell>
        </TableRow>
      </TableBody>
    </Table>
  )
}
