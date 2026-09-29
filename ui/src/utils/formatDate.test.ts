import { describe, expect, it } from 'vitest'
import { formatDateTime } from './format'
import { formatLocalIso, parseUtc } from './formatDate'

describe('parseUtc', () => {
  it('reads the API’s naive timestamps as UTC', () => {
    expect(parseUtc('2026-09-23T00:00:00').toISOString()).toBe('2026-09-23T00:00:00.000Z')
    expect(parseUtc('2026-09-23T00:00:00.123456').toISOString()).toBe('2026-09-23T00:00:00.123Z')
  })

  it('keeps an explicit offset', () => {
    expect(parseUtc('2026-09-23T02:00:00+02:00').toISOString()).toBe('2026-09-23T00:00:00.000Z')
    expect(parseUtc('2026-09-23T00:00:00Z').toISOString()).toBe('2026-09-23T00:00:00.000Z')
  })
})

describe('local-time formatting of API timestamps', () => {
  const instant = new Date('2026-09-23T10:30:00Z')

  it('renders a naive timestamp as the UTC instant it is', () => {
    expect(formatLocalIso('2026-09-23T10:30:00')).toBe(formatLocalIso(instant))
    expect(formatDateTime('2026-09-23T10:30:00')).toBe(formatDateTime(instant.toISOString()))
  })
})
