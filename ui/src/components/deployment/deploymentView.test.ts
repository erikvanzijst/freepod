import { describe, expect, it } from 'vitest'
import type { Deployment } from '../../api/types'
import { deploymentView } from './deploymentView'

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
