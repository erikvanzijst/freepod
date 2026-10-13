import type { Deployment } from '../../api/types'
import { resolveApiPath } from '../../api/client'
import { ensureUrl } from '../../utils/format'
import { formatEuro } from '../landing/usePricing'

export type Tone = 'ok' | 'busy' | 'waiting' | 'problem' | 'muted'

export interface DeploymentProblem {
  title: string
  message: string
  /** The raw error, for support; hidden behind "Show details". */
  details?: string
}

/** A deployment in the words a non-technical user reads on its card. */
export interface DeploymentView {
  appName: string
  iconUrl: string | null
  address: string | null
  url: string | null
  status: { label: string; tone: Tone; hint?: string; progress: boolean }
  problem?: DeploymentProblem
  plan?: string
  price?: string
  /** Plan and price in one phrase, without repeating "Free". */
  planLine?: string
  version?: string
  /** e.g. "v1.120.2". */
  versionLabel?: string
  since: string
  openable: boolean
  canEdit: boolean
  canRemove: boolean
}

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function status(d: Deployment): DeploymentView['status'] {
  const applied = d.applied_template?.version
  const desired = d.desired_template?.version
  switch (d.status) {
    case 'pending':
      return { label: 'Waiting for payment', tone: 'waiting', hint: 'Setup starts once your payment is confirmed.', progress: false }
    case 'provisioning':
      if ((d.generation ?? 1) <= 1) return { label: 'Setting up', tone: 'busy', hint: 'This usually takes a minute or two.', progress: true }
      if (desired && applied && desired !== applied) return { label: `Updating to ${desired}`, tone: 'busy', progress: true }
      return { label: 'Applying changes', tone: 'busy', progress: true }
    case 'ready':
      return { label: 'Running', tone: 'ok', progress: false }
    case 'error':
      return { label: 'Needs attention', tone: 'problem', progress: false }
    case 'deleting':
      return { label: 'Removing', tone: 'muted', progress: true }
    default:
      return { label: 'Unknown', tone: 'muted', progress: false }
  }
}

function problem(d: Deployment): DeploymentProblem | undefined {
  if (d.status === 'error') {
    return {
      title: 'Something went wrong',
      message: "Your app couldn't finish its last change. Saving its settings again might dislodge it. If not, please contact support.",
      details: d.last_error ?? undefined,
    }
  }
  if (d.subscription?.payment_status === 'arrears' && d.status !== 'pending') {
    return {
      title: 'Payment failed',
      message: "Your last payment didn't go through. Update your payment method to keep this app running.",
    }
  }
  return undefined
}

function price(d: Deployment): string | undefined {
  const plan = d.subscription?.plan_template
  if (!plan) return undefined
  if (plan.price_cents === 0) return 'Free'
  return `${formatEuro(plan.price_cents)}/${plan.billing_interval === 'annual' ? 'yr' : 'mo'}`
}

export function deploymentView(d: Deployment): DeploymentView {
  const product = d.desired_template?.product
  const plan = d.subscription?.plan_template?.plan?.name
  const cost = price(d)
  const planLine = plan && cost && plan.toLowerCase() === cost.toLowerCase() ? plan : [plan, cost].filter(Boolean).join(' · ') || undefined
  const version = d.applied_template?.version ?? d.desired_template?.version ?? undefined
  const openable = Boolean(
    d.hostname &&
      !(d.status === 'pending' || d.status === 'deleting' || (d.status === 'provisioning' && (d.generation ?? 1) <= 1)),
  )
  return {
    appName: product?.name ?? 'App',
    iconUrl: product?.icon_url ? resolveApiPath(product.icon_url) : null,
    address: d.hostname,
    url: d.hostname ? ensureUrl(d.hostname) : null,
    status: status(d),
    problem: problem(d),
    plan,
    price: cost,
    planLine,
    version,
    versionLabel: version ? `v${version.replace(/^v/i, '')}` : undefined,
    since: shortDate(d.created_at),
    openable,
    canEdit: d.status === 'ready' || d.status === 'error',
    canRemove: d.status !== 'deleting' && d.status !== 'deleted',
  }
}

export const toneColor: Record<Tone, string> = {
  ok: '#22C55E',
  busy: '#38BDF8',
  waiting: '#FBBF24',
  problem: '#F87171',
  muted: '#94A3B8',
}
