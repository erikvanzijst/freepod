import { describe, expect, it } from 'vitest'
import indexHtml from '../../index.html?raw'
import llmsTxt from '../../public/llms.txt?raw'

const UNLISTED = new Set(['appstudio', 'custom'])

const catalogSlugs = Object.keys(import.meta.glob('../../../products/catalog/*/*.yaml'))
  .map((path) => path.split('/').at(-2)!)
  .filter((slug) => !UNLISTED.has(slug))

describe.each([
  ['index.html', indexHtml],
  ['llms.txt', llmsTxt],
])('static instructions in %s', (_, content) => {
  it.each([
    'Freepod Apps',
    'Freepod for Developers',
    'https://freepod.eu/apps',
    'uv tool install freepod',
    'freepod skill install',
    'freepod login',
    'freepod deploy',
    'https://freepod.eu/dev',
    'https://freepod.eu/docs/developers/coding-agents',
  ])('mention %s', (text) => {
    expect(content).toContain(text)
  })

  it('lists every catalog app', () => {
    expect(catalogSlugs.length).toBeGreaterThan(0)
    for (const slug of catalogSlugs) {
      expect(content).toContain(`https://freepod.eu/apps/${slug}`)
    }
  })
})
