// Reads product metadata from products/catalog, the catalog's source of truth,
// and fails the build unless every catalog product has a page under
// apps/products/ and every page has a product.
//
// The UI image builds with ui/ as its context, so the Docker build passes the
// catalog in as a named build context and points CATALOG_DIR at it.
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { basename, extname, join, resolve } from 'node:path'
import yaml from 'js-yaml'

// Not a catalog app: the developer deployment target, documented under /developers.
const EXCLUDED = new Set(['custom'])

export function catalogDir(siteDir) {
  return process.env.CATALOG_DIR ?? resolve(siteDir, '..', '..', 'products', 'catalog')
}

// Each product is a folder holding `<slug>.yaml` and the assets it names.
function readDocuments(dir) {
  if (!existsSync(dir)) throw new Error(`catalog not found at ${dir}; set CATALOG_DIR`)
  return readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory() && !e.name.startsWith('.'))
    .map((e) => e.name)
    .sort()
    .map((slug) => ({ slug, product: yaml.load(readFileSync(join(dir, slug, `${slug}.yaml`), 'utf8')).product }))
    .filter(({ slug }) => !EXCLUDED.has(slug))
}

/**
 * Copy each product's icon to `<siteDir>/.catalog-icons/<slug>.<ext>` and
 * return that directory, for the site to serve as a static directory. Copying
 * keeps the rest of each catalog folder, screenshots included, out of the site.
 */
export function stageIcons(siteDir) {
  const dir = catalogDir(siteDir)
  const out = join(siteDir, '.catalog-icons')
  rmSync(out, { recursive: true, force: true })
  mkdirSync(out, { recursive: true })
  for (const { slug, product } of readDocuments(dir)) {
    if (product.icon) copyFileSync(join(dir, slug, product.icon), join(out, `${slug}${extname(product.icon)}`))
  }
  return out
}

function readProducts(dir) {
  return readDocuments(dir).map(({ slug, product }) => ({
    slug,
    name: product.name,
    tagline: product.tagline ?? null,
    category: product.category ?? null,
    // Served from the staged icon directory (see stageIcons).
    icon: product.icon ? `/${slug}${extname(product.icon)}` : null,
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
    getPathsToWatch: () => [join(dir, '*', '*.yaml'), join(pagesDir, '*')],
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
