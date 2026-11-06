import { describe, expect, it } from 'vitest'
import type { Deployment } from '../../api/types'
import { deploymentView, powerLabel } from './deploymentView'

function deployment(overrides: Partial<Deployment> = {}): Deployment {
  return {
    id: 'd1',
    desired_template_id: 1,
    hostname: 'photos.example.test',
    user_id: 1,
    created_at: '2026-08-01T00:00:00Z',
    user: { id: 1, email: 'o@example.com', is_admin: false, created_at: '2026-08-01T00:00:00Z' },
    desired_template: { id: 1, version: '1.120.2', product: { id: 2, name: 'Immich' } } as Deployment['desired_template'],
    applied_template: { id: 1, version: '1.120.2', product: { id: 2, name: 'Immich' } } as Deployment['desired_template'],
    name: 'immich-x1',
    namespace: 'ns',
    status: 'ready',
    power: { desired: 'running', applied: 'running' },
    generation: 1,
    ...overrides,
  }
}

function subscription(planName: string, priceCents: number, paymentStatus: 'current' | 'arrears' = 'current') {
  return {
    subscription: {
      id: 1,
      plan_template_id: 1,
      user_id: 1,
      status: 'active',
      payment_status: paymentStatus,
      created_at: '2026-08-01T00:00:00Z',
      plan_template: { id: 1, plan_id: 1, price_cents: priceCents, billing_interval: 'monthly', created_at: '', plan: { name: planName } },
    },
  } as Partial<Deployment>
}

describe('deploymentView status', () => {
  it.each([
    [{ status: 'ready' }, 'Running', 'ok'],
    [{ status: 'pending' }, 'Waiting for payment', 'waiting'],
    [{ status: 'provisioning', generation: 1 }, 'Setting up', 'busy'],
    [{ status: 'error' }, 'Needs attention', 'problem'],
    [{ status: 'deleting' }, 'Removing', 'muted'],
  ] as const)('%o reads as %s', (overrides, label, tone) => {
    const view = deploymentView(deployment(overrides as Partial<Deployment>))
    expect(view.status.label).toBe(label)
    expect(view.status.tone).toBe(tone)
  })

  it('names the version an update moves to', () => {
    const view = deploymentView(
      deployment({
        status: 'provisioning',
        generation: 3,
        desired_template: { ...deployment().desired_template, version: '1.121.0' },
      }),
    )
    expect(view.status.label).toBe('Updating to 1.121.0')
  })

  it('says "Applying changes" when the version stays the same', () => {
    expect(deploymentView(deployment({ status: 'provisioning', generation: 3 })).status.label).toBe('Applying changes')
  })

  it('cannot be opened before its first setup finishes', () => {
    expect(deploymentView(deployment({ status: 'provisioning', generation: 1 })).openable).toBe(false)
    expect(deploymentView(deployment({ status: 'provisioning', generation: 3 })).openable).toBe(true)
  })
})

describe('deploymentView problems', () => {
  it('explains an error and keeps the raw message as details', () => {
    const problem = deploymentView(deployment({ status: 'error', last_error: 'helm: timed out' })).problem
    expect(problem?.title).toBe('Something went wrong')
    expect(problem?.message).toContain('contact support')
    expect(problem?.details).toBe('helm: timed out')
  })

  it('links to support with the deployment and its error filled in', () => {
    const link = deploymentView(deployment({ status: 'error', last_error: 'helm: timed out' })).problem?.support ?? ''
    expect(link).toMatch(/^mailto:support@freepod\.eu\?/)
    const params = new URLSearchParams(link.split('?')[1])
    expect(params.get('subject')).toBe('Help with photos.example.test')
    expect(params.get('body')).toContain('Deployment: d1')
    expect(params.get('body')).toContain('Error: helm: timed out')
  })

  it('flags a failed payment on a running app', () => {
    expect(deploymentView(deployment(subscription('Personal', 499, 'arrears'))).problem?.title).toBe('Payment failed')
  })

  it('has none when all is well', () => {
    expect(deploymentView(deployment()).problem).toBeUndefined()
  })
})

describe('deploymentView plan and version', () => {
  it('joins plan and price', () => {
    expect(deploymentView(deployment(subscription('Personal', 499))).planLine).toBe('Personal · €4.99/mo')
  })

  it('does not repeat "Free"', () => {
    expect(deploymentView(deployment(subscription('Free', 0))).planLine).toBe('Free')
  })

  it('labels the running version', () => {
    expect(deploymentView(deployment()).versionLabel).toBe('v1.120.2')
  })
})

describe('deploymentView docs', () => {
  const withSlug = (slug: string | null) =>
    deployment({ desired_template: { id: 1, product: { id: 2, name: 'Immich', slug } } as Deployment['desired_template'] })

  it('links a catalog app to its product guide', () => {
    expect(deploymentView(withSlug('immich')).docsUrl).toBe('/docs/apps/products/immich')
  })

  it('links a custom deployment to the developer docs', () => {
    expect(deploymentView(withSlug('custom')).docsUrl).toBe('/docs/developers')
  })

  it('has no docs for a product outside the catalog', () => {
    expect(deploymentView(withSlug(null)).docsUrl).toBeNull()
  })
})

describe('deploymentView power', () => {
  const power = (desired: 'running' | 'stopped', applied: 'running' | 'stopped', reason: 'manual' | 'payment' | null = null) =>
    ({ power: { desired, applied, reason } }) as Partial<Deployment>

  it.each([
    [power('stopped', 'stopped', 'manual'), 'Stopped', 'muted', false],
    [power('stopped', 'running', 'manual'), 'Stopping', 'busy', true],
    [power('running', 'stopped'), 'Starting', 'busy', true],
    [power('running', 'running'), 'Running', 'ok', false],
  ] as const)('%o reads as %s', (overrides, label, tone, progress) => {
    const view = deploymentView(deployment(overrides))
    expect(view.status).toMatchObject({ label, tone, progress })
  })

  it('keeps the existing labels while not ready', () => {
    expect(deploymentView(deployment({ status: 'error', ...power('stopped', 'stopped', 'manual') })).status.label).toBe(
      'Needs attention',
    )
    expect(deploymentView(deployment({ status: 'provisioning', generation: 3, ...power('stopped', 'stopped', 'manual') })).status.label).toBe(
      'Applying changes',
    )
  })

  it('offers Stop on a ready app meant to be running', () => {
    expect(deploymentView(deployment(power('running', 'running')))).toMatchObject({ canStop: true, canStart: false })
    expect(deploymentView(deployment(power('running', 'stopped')))).toMatchObject({ canStop: true, canStart: false })
  })

  it('offers Start in place of Stop on an app its owner stopped', () => {
    expect(deploymentView(deployment(power('stopped', 'stopped', 'manual')))).toMatchObject({ canStop: false, canStart: true })
    expect(deploymentView(deployment(power('stopped', 'running', 'manual')))).toMatchObject({ canStop: false, canStart: true })
  })

  it('offers neither for a stop the owner cannot lift', () => {
    expect(deploymentView(deployment(power('stopped', 'stopped', 'payment')))).toMatchObject({ canStop: false, canStart: false })
  })

  it.each(['error', 'provisioning', 'pending', 'deleting'] as const)('offers neither while %s', (status) => {
    expect(deploymentView(deployment({ status, ...power('stopped', 'stopped', 'manual') }))).toMatchObject({
      canStop: false,
      canStart: false,
    })
    expect(deploymentView(deployment({ status }))).toMatchObject({ canStop: false, canStart: false })
  })
})

describe('powerLabel', () => {
  const power = (desired: 'running' | 'stopped', applied: 'running' | 'stopped', reason: 'manual' | 'payment' | null = null) =>
    ({ power: { desired, applied, reason } }) as Partial<Deployment>

  it.each([
    [power('running', 'running'), 'Running'],
    [power('stopped', 'running', 'manual'), 'Stopping'],
    [power('stopped', 'stopped', 'manual'), 'Stopped'],
    [power('running', 'stopped'), 'Starting'],
    [power('stopped', 'stopped', 'payment'), 'Stopped (payment)'],
    [power('stopped', 'running', 'payment'), 'Stopping (payment)'],
  ] as const)('%o reads as %s', (overrides, label) => {
    expect(powerLabel(deployment(overrides))).toBe(label)
  })

  it('reads the power whatever the status', () => {
    expect(powerLabel(deployment({ status: 'error', ...power('stopped', 'stopped', 'manual') }))).toBe('Stopped')
  })
})
