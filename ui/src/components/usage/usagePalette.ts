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
 * Color series by their position in `order`, a ranking that must not depend
 * on the period shown. Keys missing from it rank after, alphabetically. When
 * there are more entities than colors, the last slot becomes "Other".
 */
export function colorSeries(
  series: UsageSeries[],
  order: string[],
  label: (key: string) => string,
): ColoredSeries[] {
  const known = new Set(order)
  const ranking = [
    ...order,
    ...series.map((s) => s.key).filter((key) => !known.has(key)).sort(),
  ]
  const capacity = ranking.length <= CATEGORICAL.length ? CATEGORICAL.length : CATEGORICAL.length - 1
  const slot = (key: string) => ranking.indexOf(key)

  const colored: ColoredSeries[] = series
    .filter((s) => slot(s.key) < capacity)
    .sort((a, b) => slot(a.key) - slot(b.key))
    .map((s) => ({ ...s, label: label(s.key), color: CATEGORICAL[slot(s.key)] }))

  const overflow = series.filter((s) => slot(s.key) >= capacity)
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
