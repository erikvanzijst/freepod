import type { UsageSeries } from './usageModel'

/**
 * Categorical steps for the app's dark surface, in a fixed order validated for
 * color-vision deficiency against `ink.base`. A series keeps its slot for as
 * long as its entity exists, so toggling or paging never repaints survivors.
 */
export const CATEGORICAL = [
  '#3987e5', // blue
  '#d95926', // orange
  '#199e70', // aqua
  '#c98500', // yellow
  '#d55181', // magenta
  '#008300', // green
  '#9085e9', // violet
  '#e66767', // red
]

/** Everything past the palette folds into one neutral series. */
export const OTHER_COLOR = '#6F7C9B'
export const OTHER_KEY = '__other__'

export interface ColoredSeries extends UsageSeries {
  label: string
  color: string
}

/**
 * Color series by their position in `order`, a ranking that must not depend on
 * the period shown. Keys missing from it rank after, alphabetically.
 *
 * When every ranked entity fits the palette, each owns its color for good.
 * When not, only the series present share it, still in ranked order, and past
 * the palette the smallest by cost fold into "Other" -- never an arbitrary
 * tail of the ranking, which could hide the heaviest entity in gray.
 */
export function colorSeries(
  series: UsageSeries[],
  order: string[],
  label: (key: string) => string,
): ColoredSeries[] {
  const present = new Set(series.map((s) => s.key))
  const known = new Set(order)
  const ranking = [...order, ...[...present].filter((key) => !known.has(key)).sort()]

  let slots: string[]
  let shown: UsageSeries[]
  if (ranking.length <= CATEGORICAL.length) {
    slots = ranking
    shown = series
  } else if (present.size <= CATEGORICAL.length) {
    slots = ranking.filter((key) => present.has(key))
    shown = series
  } else {
    const kept = new Set(
      [...series]
        .sort((a, b) => b.total - a.total)
        .slice(0, CATEGORICAL.length - 1)
        .map((s) => s.key),
    )
    slots = ranking.filter((key) => kept.has(key))
    shown = series.filter((s) => kept.has(s.key))
  }

  const colored: ColoredSeries[] = shown
    .map((s) => ({ ...s, label: label(s.key), color: CATEGORICAL[slots.indexOf(s.key)] }))
    .sort((a, b) => slots.indexOf(a.key) - slots.indexOf(b.key))

  const overflow = series.filter((s) => !shown.includes(s))
  if (overflow.length > 0) {
    colored.push({
      key: OTHER_KEY,
      label: `Other (${overflow.length})`,
      color: OTHER_COLOR,
      total: overflow.reduce((sum, s) => sum + s.total, 0),
      data: overflow[0].data.map((_, i) => {
        const values = overflow.map((s) => s.data[i]).filter((v): v is number => v != null)
        return values.length ? values.reduce((a, b) => a + b, 0) : null
      }),
    })
  }
  return colored
}
