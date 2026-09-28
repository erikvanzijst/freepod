import { describe, expect, it } from 'vitest'
import { LEGAL_DOCS, LEGAL_NAV } from './index'

describe('legal document registry', () => {
  // Guard against a document whose **Effective date:** line was reformatted or
  // removed: every registered document must expose a valid ISO-8601 version,
  // otherwise a deployment could record an empty or wrong consent version.
  it.each(Object.values(LEGAL_DOCS))('$slug exposes a valid ISO effective date', (doc) => {
    expect(doc.version).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('parses the Terms of Service effective date', () => {
    expect(LEGAL_DOCS.terms.version).toBe('2026-09-27')
  })

  it('keeps the nav list and registry in sync', () => {
    expect(LEGAL_NAV.map((d) => d.slug)).toEqual(['terms', 'privacy', 'aup', 'dpa'])
  })
})
