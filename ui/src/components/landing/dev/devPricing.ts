import type { SvgIconComponent } from '@mui/icons-material'
import MemoryRoundedIcon from '@mui/icons-material/MemoryRounded'
import DeveloperBoardRoundedIcon from '@mui/icons-material/DeveloperBoardRounded'
import StorageRoundedIcon from '@mui/icons-material/StorageRounded'
import CloudQueueRoundedIcon from '@mui/icons-material/CloudQueueRounded'
import { accent, fg, MONO } from '../landingTokens'

/** Hours in a billing month, as cloud providers count it (365 × 24 / 12). */
export const HOURS_PER_MONTH = 730

export type ResourceId = 'cpu' | 'memory' | 'postgres' | 'objects'

export interface ResourceRate {
  id: ResourceId
  icon: SvgIconComponent
  color: string
  name: string
  /** The least billed per hour: the app's reservation. Storage has none. */
  floor: number
  /** What one unit is: "vCPU", "GiB". */
  unit: string
  /** Euros per unit per hour, as in the `usage_rate` table. */
  hourly: number
  /** Decimals when shown per month. */
  digits: number
}

export const rates: ResourceRate[] = [
  {
    id: 'cpu',
    icon: DeveloperBoardRoundedIcon,
    color: accent.blue,
    name: 'vCPU',
    floor: 0.01,
    unit: 'vCPU',
    hourly: 0.015437,
    digits: 2,
  },
  {
    id: 'memory',
    icon: MemoryRoundedIcon,
    color: '#8B6CFF',
    name: 'Memory',
    floor: 0.125,
    unit: 'GiB',
    hourly: 0.002069,
    digits: 2,
  },
  {
    id: 'postgres',
    icon: StorageRoundedIcon,
    color: accent.cyan,
    name: 'Postgres',
    floor: 0,
    unit: 'GiB',
    hourly: 0.000171,
    digits: 3,
  },
  {
    id: 'objects',
    icon: CloudQueueRoundedIcon,
    color: accent.magenta,
    name: 'Object storage',
    floor: 0,
    unit: 'GiB',
    hourly: 0.0000274,
    digits: 2,
  },
]

export const monthly = (rate: ResourceRate) => rate.hourly * HOURS_PER_MONTH

/**
 * Average resource levels over a month, per resource. A small personal app on
 * Freepod measured over two weeks: it idles at its reservation, with a few MiB
 * of Postgres and about one build a day.
 */
export type Usage = Record<ResourceId, number>

export const personalApp: Usage = { cpu: 0.012, memory: 0.14, postgres: 0.008, objects: 0 }

/** The example app's builds a month and the average cost of one build, measured on Freepod. */
export const personalAppBuilds = { count: 30, eachEuros: 0.0002 }

export function monthlyCost(usage: Usage): number {
  return rates.reduce((sum, rate) => sum + usage[rate.id] * monthly(rate), 0)
}

/** What an app costs a month when it idles at its reservation. */
export const floorCost = rates.reduce((sum, rate) => sum + rate.floor * monthly(rate), 0)

export const personalAppTotal = monthlyCost(personalApp) + personalAppBuilds.count * personalAppBuilds.eachEuros

export const euro = (value: number, digits = 2) => `€${value.toFixed(digits)}`

/** A rate's monthly price with enough digits to read: €11.27, €0.125, €0.02. */
export const monthlyPrice = (rate: ResourceRate) => euro(monthly(rate), rate.digits)

/** Three significant digits: €0.0154, €0.0000274. */
export const hourlyPrice = (rate: ResourceRate) => `€${rate.hourly.toPrecision(3)}`

export const pricingNotes = {
  builds: 'Builds are billed at the same vCPU and memory rates, from the moment they start to the moment they finish.',
  traffic: 'No charge for traffic, requests or bandwidth.',
  disclaimer: 'Prices in euros, excluding VAT. Pricing subject to change.',
}

/** Small uppercase mono label used across the pricing section. */
export const eyebrowSx = { fontFamily: MONO, fontSize: 12, letterSpacing: '0.18em', textTransform: 'uppercase', color: fg.faint } as const
