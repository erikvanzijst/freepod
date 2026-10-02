// Reads product metadata from products/catalog, the catalog's source of truth,
// and fails the build unless every catalog product has a page under
// apps/products/ and every page has a product.
//
// The UI image builds with ui/ as its context, so the Docker build passes the
// catalog in as a named build context and points CATALOG_DIR at it.
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { basename, extname, join, resolve } from 'node:path'
import yaml from 'js-yaml'

// Not a catalog app: the developer deployment target, documented under /developers.
const EXCLUDED = new Set(['custom'])

export function catalogDir(siteDir) {
  return process.env.CATALOG_DIR ?? resolve(siteDir, '..', '..', 'products', 'catalog')
}

function readProducts(dir) {
  if (!existsSync(dir)) throw new Error(`catalog not found at ${dir}; set CATALOG_DIR`)
  return readdirSync(dir)
    .filter((f) => f.endsWith('.yaml'))
    .sort()
    .map((f) => yaml.load(readFileSync(join(dir, f), 'utf8')).product)
    .filter((p) => !EXCLUDED.has(p.slug))
    .map((p) => ({
      slug: p.slug,
      name: p.name,
      description: p.description,
      category: p.category ?? null,
      // Served from the catalog's icons directory, a static directory of the site.
      icon: `/${basename(p.icon)}`,
    }))
}

function checkPages(products, pagesDir) {
  const pages = readdirSync(pagesDir)
    .filter((f) => /\.mdx?$/.test(f))
    .map((f) => basename(f, extname(f)))
  const slugs = products.map((p) => p.slug)
  const problems = [
    ...slugs.filter((s) => !pages.includes(s)).map((s) => `no page apps/products/${s}.mdx for catalog product ${s}`),
    ...pages.filter((p) => !slugs.includes(p)).map((p) => `apps/products/${p} has no catalog product`),
  ]
  if (problems.length) throw new Error(problems.join('\n'))
}

export default function catalogPlugin(context) {
  const dir = catalogDir(context.siteDir)
  const pagesDir = join(context.siteDir, 'apps', 'products')
  return {
    name: 'freepod-catalog',
    getPathsToWatch: () => [join(dir, '*.yaml'), join(pagesDir, '*')],
    async loadContent() {
      const products = readProducts(dir)
      checkPages(products, pagesDir)
      return products
    },
    async contentLoaded({ content, actions }) {
      actions.setGlobalData({ products: content })
    },
  }
}
