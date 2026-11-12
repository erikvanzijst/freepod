import { describe, expect, it } from 'vitest'
import type { Deployment, PowerState } from '../api/types'
import { isTransitionalStatus, listingRefetchInterval, statusColor } from './deploymentStatus'

describe('deployment status helpers', () => {
  it('maps known statuses to UI colors', () => {
    expect(statusColor('provisioning')).toBe('warning')
    expect(statusColor('ready')).toBe('success')
    expect(statusColor('deleting')).toBe('warning')
    expect(statusColor('deleted')).toBe('default')
    expect(statusColor('error')).toBe('error')
  })

  it('treats only provisioning and deleting as transitional', () => {
    expect(isTransitionalStatus('provisioning')).toBe(true)
    expect(isTransitionalStatus('deleting')).toBe(true)
    expect(isTransitionalStatus('ready')).toBe(false)
    expect(isTransitionalStatus('deleted')).toBe(false)
    expect(isTransitionalStatus('error')).toBe(false)
  })
})

describe('listingRefetchInterval', () => {
  const dep = (status: Deployment['status'], desired: PowerState, applied: PowerState, reason?: 'maintenance') =>
    ({ id: 'd1', status, power: { desired, applied, reason } }) as Deployment

  it('polls while a stop is being applied, and stops once it is', () => {
    expect(listingRefetchInterval([dep('ready', 'running', 'running')])).toBe(false)
    expect(listingRefetchInterval([dep('ready', 'stopped', 'running')])).toBe(3000)
    expect(listingRefetchInterval([dep('ready', 'stopped', 'stopped')])).toBe(false)
  })

  it('polls while a start is being applied', () => {
    expect(listingRefetchInterval([dep('ready', 'running', 'stopped')])).toBe(3000)
  })

  it('still polls for transitional statuses', () => {
    expect(listingRefetchInterval([dep('ready', 'running', 'running'), dep('provisioning', 'running', 'running')])).toBe(3000)
  })

  it('keeps polling while under maintenance, until it is lifted', () => {
    expect(listingRefetchInterval([dep('ready', 'stopped', 'stopped', 'maintenance')])).toBe(10000)
    expect(listingRefetchInterval([dep('ready', 'running', 'running')])).toBe(false)
  })
})
