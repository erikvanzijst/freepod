import { useState } from 'react'
import { monthly, personalApp, personalAppBuilds, rates, type ResourceId, type ResourceRate, type Usage } from './devPricing'

/** Slider bounds per resource; storage may also be zero, at the far left. */
const bounds: Record<ResourceId, { min: number; max: number; zero: boolean }> = {
  cpu: { min: 0.01, max: 4, zero: false },
  memory: { min: 0.125, max: 8, zero: false },
  postgres: { min: 1 / 1024, max: 100, zero: true },
  objects: { min: 1 / 1024, max: 1000, zero: true },
}

/** Map a slider position (0–100) to a resource level on a log scale, and back. */
export function toLevel(id: ResourceId, pos: number): number {
  const { min, max, zero } = bounds[id]
  if (zero && pos === 0) return 0
  return min * (max / min) ** (pos / 100)
}

export function toPos(id: ResourceId, level: number): number {
  const { min, max } = bounds[id]
  if (level <= 0) return 0
  return Math.max(0, Math.min(100, (100 * Math.log(level / min)) / Math.log(max / min)))
}

export function formatLevel(rate: ResourceRate, level: number): string {
  if (level === 0) return 'none'
  if (rate.unit === 'vCPU') return `${level < 0.1 ? level.toFixed(3) : level.toFixed(2)} vCPU`
  if (level < 1) return `${Math.round(level * 1024)} MiB`
  return `${level < 10 ? level.toFixed(1) : Math.round(level)} GiB`
}

export const buildsColor = '#F59E0B'

/** Each preset's resource levels, and how many builds it runs a month. */
export const presets: { label: string; note: string; usage: Usage; builds: number }[] = [
  { label: 'Personal app', note: 'Measured on a small app running on Freepod.', usage: personalApp, builds: personalAppBuilds.count },
  { label: 'Side project', note: 'A little traffic and a few GiB of uploads.', usage: { cpu: 0.05, memory: 0.25, postgres: 0.5, objects: 5 }, builds: 34 },
  { label: 'Busy API', note: 'Half a vCPU around the clock, deployed a few times a day.', usage: { cpu: 0.5, memory: 1, postgres: 10, objects: 50 }, builds: 120 },
]

/** The estimator's state: resource levels, the chosen preset, and what they cost. */
export function useEstimate() {
  const [usage, setUsage] = useState<Usage>(personalApp)
  const [preset, setPreset] = useState<string | null>(presets[0].label)
  // Kept when a slider moves: there is no builds slider, so the last preset's count stands.
  const [buildCount, setBuildCount] = useState(presets[0].builds)
  const builds = buildCount * personalAppBuilds.eachEuros
  const costs = rates.map((rate) => ({ rate, cost: usage[rate.id] * monthly(rate) }))
  const total = costs.reduce((sum, c) => sum + c.cost, 0) + builds

  return {
    usage,
    preset,
    buildCount,
    builds,
    costs,
    total,
    note: presets.find((p) => p.label === preset)?.note ?? 'Your own mix.',
    choose: (label: string) => {
      const p = presets.find((x) => x.label === label)
      if (!p) return
      setUsage(p.usage)
      setBuildCount(p.builds)
      setPreset(p.label)
    },
    set: (id: ResourceId, level: number) => {
      setUsage((u) => ({ ...u, [id]: level }))
      setPreset(null)
    },
  }
}

export type Estimate = ReturnType<typeof useEstimate>
