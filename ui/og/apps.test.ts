// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { readCatalogApps, renderAppCard } from './apps'

describe('readCatalogApps', () => {
  it('reads every storefront app from the catalog, skipping custom', () => {
    const apps = readCatalogApps()
    const slugs = apps.map((app) => app.slug)
    expect(slugs).toContain('immich')
    expect(slugs).not.toContain('custom')
    expect(slugs).toEqual([...slugs].sort())
  })

  it('takes the first paragraph of the description as the lead', () => {
    const dir = mkdtempSync(join(tmpdir(), 'catalog-'))
    mkdirSync(join(dir, 'demo'))
    writeFileSync(
      join(dir, 'demo', 'demo.yaml'),
      'product:\n  name: Demo\n  tagline: A demo.\n  description: |-\n    First\n    paragraph.\n\n    Second paragraph.\n',
    )
    expect(readCatalogApps(dir)).toEqual([
      { slug: 'demo', name: 'Demo', tagline: 'A demo.', lead: 'First paragraph.' },
    ])
  })

  it('fails when the catalog is missing', () => {
    expect(() => readCatalogApps(join(tmpdir(), 'no-such-catalog'))).toThrow(/CATALOG_DIR/)
  })
})

describe('renderAppCard', () => {
  it('renders a 1200x630 PNG', async () => {
    const immich = readCatalogApps().find((app) => app.slug === 'immich')!
    const png = await renderAppCard(immich)
    expect(png.subarray(1, 4).toString()).toBe('PNG')
    expect(png.readUInt32BE(16)).toBe(1200)
    expect(png.readUInt32BE(20)).toBe(630)
  })
})
