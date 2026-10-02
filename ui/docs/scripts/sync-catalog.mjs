#!/usr/bin/env node
// Copies product metadata and icons from products/catalog/ into the docs site,
// which the UI image builds without the rest of the repo in its context.
//
//   node scripts/sync-catalog.mjs          write src/data/catalog.json + static/img/products/
//   node scripts/sync-catalog.mjs --check  fail if the copy is stale, a product lacks a
//                                          page under apps/products/, or a page lacks a product
//
// --check reads products/catalog/ when it exists (CI, local checkout) and only
// verifies page coverage against the committed copy otherwise (Docker build).
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { basename, dirname, extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import yaml from 'js-yaml'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const catalogDir = join(root, '..', '..', 'products', 'catalog')
const dataFile = join(root, 'src', 'data', 'catalog.json')
const iconDir = join(root, 'static', 'img', 'products')
const pagesDir = join(root, 'apps', 'products')

// Not a catalog app: the developer deployment target, documented under /developers.
const EXCLUDED = new Set(['custom'])

function readCatalog() {
  const products = []
  for (const file of readdirSync(catalogDir).filter((f) => f.endsWith('.yaml')).sort()) {
    const { product } = yaml.load(readFileSync(join(catalogDir, file), 'utf8'))
    if (EXCLUDED.has(product.slug)) continue
    const iconFile = `${product.slug}${extname(product.icon)}`
    products.push({
      slug: product.slug,
      name: product.name,
      description: product.description,
      category: product.category ?? null,
      icon: `img/products/${iconFile}`,
      iconSource: join(catalogDir, product.icon),
      iconFile,
    })
  }
  return products
}

const toJson = (products) =>
  JSON.stringify(
    products.map(({ iconSource: _s, iconFile: _f, ...rest }) => rest),
    null,
    2,
  ) + '\n'

function sync() {
  const products = readCatalog()
  mkdirSync(dirname(dataFile), { recursive: true })
  writeFileSync(dataFile, toJson(products))
  rmSync(iconDir, { recursive: true, force: true })
  mkdirSync(iconDir, { recursive: true })
  for (const p of products) writeFileSync(join(iconDir, p.iconFile), readFileSync(p.iconSource))
  console.log(`synced ${products.length} products`)
}

function check() {
  const problems = []
  let slugs
  if (existsSync(catalogDir)) {
    const products = readCatalog()
    slugs = products.map((p) => p.slug)
    if (!existsSync(dataFile) || readFileSync(dataFile, 'utf8') !== toJson(products)) {
      problems.push('src/data/catalog.json is stale')
    }
    for (const p of products) {
      const copy = join(iconDir, p.iconFile)
      if (!existsSync(copy) || !readFileSync(copy).equals(readFileSync(p.iconSource))) {
        problems.push(`static/img/products/${p.iconFile} is stale`)
      }
    }
    if (problems.length) problems.push('run `npm run catalog:sync` in ui/docs')
  } else {
    slugs = JSON.parse(readFileSync(dataFile, 'utf8')).map((p) => p.slug)
  }

  const pages = existsSync(pagesDir)
    ? readdirSync(pagesDir)
        .filter((f) => /\.mdx?$/.test(f) && !f.startsWith('index.'))
        .map((f) => basename(f, extname(f)))
    : []
  for (const slug of slugs) {
    if (!pages.includes(slug)) problems.push(`no page apps/products/${slug}.md for catalog product ${slug}`)
  }
  for (const page of pages) {
    if (!slugs.includes(page)) problems.push(`apps/products/${page} has no catalog product`)
  }

  if (problems.length) {
    for (const p of problems) console.error(p)
    process.exit(1)
  }
  console.log(`catalog ok: ${slugs.length} products, all documented`)
}

if (process.argv.includes('--check')) check()
else sync()
