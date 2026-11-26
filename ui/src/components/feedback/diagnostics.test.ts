import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  DIAGNOSTICS_LIMIT,
  installDiagnostics,
  record,
  recordApiFailure,
  snapshot,
  reset,
} from './diagnostics'

let uninstall = () => {}

afterEach(() => {
  uninstall()
  uninstall = () => {}
  reset()
})

describe('diagnostics recorder', () => {
  it('keeps entries in order and only the newest 20', () => {
    for (let i = 0; i < 30; i++) record({ kind: 'error', message: `e${i}` })
    const entries = snapshot()
    expect(entries).toHaveLength(DIAGNOSTICS_LIMIT)
    expect(entries[0].message).toBe('e10')
    expect(entries.at(-1)?.message).toBe('e29')
    expect(entries[0].at).toMatch(/^\d{4}-\d{2}-\d{2}T/)
  })

  it('records an API failure as method, path and status only', () => {
    recordApiFailure('post', '/api/users/7/deployments?token=secret#x', 500)
    recordApiFailure('GET', '/api/me', null)
    expect(snapshot()).toMatchObject([
      { kind: 'api', method: 'POST', path: '/api/users/7/deployments', status: 500 },
      { kind: 'api', method: 'GET', path: '/api/me', message: 'network error' },
    ])
  })

  it('wraps console.error and still calls the original', () => {
    const original = vi.fn()
    const sink = { error: original } as unknown as Console
    uninstall = installDiagnostics(window, sink)
    sink.error('boom', { a: 1 })
    expect(original).toHaveBeenCalledWith('boom', { a: 1 })
    expect(snapshot()[0]).toMatchObject({ kind: 'console', message: 'boom {"a":1}' })
  })

  it('records uncaught errors and rejections', () => {
    uninstall = installDiagnostics(window, { error: vi.fn() } as unknown as Console)
    window.dispatchEvent(new ErrorEvent('error', { message: 'Kaboom', filename: '/assets/x.js', lineno: 3, colno: 9 }))
    const rejection = new Event('unhandledrejection') as PromiseRejectionEvent
    Object.defineProperty(rejection, 'reason', { value: new Error('nope') })
    window.dispatchEvent(rejection)
    const [error, rejected] = snapshot()
    expect(error).toMatchObject({ kind: 'error', message: 'Kaboom', source: '/assets/x.js:3:9' })
    expect(rejected.kind).toBe('rejection')
    expect(rejected.message).toContain('nope')
  })

  it('clips long messages to 500 characters', () => {
    record({ kind: 'console', message: 'x'.repeat(900) })
    expect(snapshot()[0].message).toHaveLength(500)
  })
})
