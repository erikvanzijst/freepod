import { describe, expect, it } from 'vitest'
import { isAppRoute } from './links'

describe('isAppRoute', () => {
  it.each(['/', '/dev', '/settings/domain', '/legal/terms'])('routes %s in the app', (href) => {
    expect(isAppRoute(href)).toBe(true)
  })

  it.each(['/docs', '/docs/', '/docs/developers', '/#pricing', '#apps', 'https://example.com'])(
    'loads %s as a page',
    (href) => {
      expect(isAppRoute(href)).toBe(false)
    },
  )

  it('does not mistake a path that merely starts with "docs"', () => {
    expect(isAppRoute('/docsearch')).toBe(true)
  })
})
