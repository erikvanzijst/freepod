/**
 * Link previews for the catalog's app pages (/apps/:slug), built from
 * products/catalog, the catalog's source of truth: one entry per app, and a
 * 1200x630 card image for each, rendered without a browser (satori lays the
 * card out as SVG, resvg rasterizes it). The `pageMeta` Vite plugin turns
 * these into each page's HTML and image.
 *
 * The UI image builds with ui/ as its context, so the Docker build passes the
 * catalog in as a named build context and points CATALOG_DIR at it.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import yaml from 'js-yaml'
import satori from 'satori'
import { Resvg } from '@resvg/resvg-js'

/** Not a storefront app: the developer deployment target, which has /dev. */
const EXCLUDED = new Set(['custom'])

export interface CatalogApp {
  slug: string
  name: string
  tagline?: string
  /** The description's first paragraph, for search results. */
  lead?: string
  category?: string
  replaces?: string
  /** Absolute path to the icon file. */
  icon?: string
}

export function catalogDir(): string {
  return process.env.CATALOG_DIR ?? fileURLToPath(new URL('../../products/catalog', import.meta.url))
}

interface CatalogDocument {
  product: {
    name: string
    tagline?: string
    description?: string
    category?: string
    replaces?: string
    icon?: string
  }
}

/** Every storefront app in the catalog, in slug order. */
export function readCatalogApps(dir = catalogDir()): CatalogApp[] {
  if (!existsSync(dir)) throw new Error(`catalog not found at ${dir}; set CATALOG_DIR`)
  return readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory() && !e.name.startsWith('.') && !EXCLUDED.has(e.name))
    .map((e) => e.name)
    .sort()
    .map((slug) => {
      const { product } = yaml.load(readFileSync(join(dir, slug, `${slug}.yaml`), 'utf8')) as CatalogDocument
      return {
        slug,
        name: product.name,
        tagline: product.tagline,
        lead: product.description?.split(/\n\s*\n/)[0].replace(/\s+/g, ' ').trim() || undefined,
        category: product.category,
        replaces: product.replaces,
        icon: product.icon ? join(dir, slug, product.icon) : undefined,
      }
    })
}

const font = (pkg: string, file: string) =>
  readFileSync(fileURLToPath(new URL(`../node_modules/@fontsource/${pkg}/files/${file}`, import.meta.url)))

// satori reads TTF, OTF and WOFF, not WOFF2, and no variable fonts: hence the
// static @fontsource packages rather than the variable ones the site uses.
let fonts: Parameters<typeof satori>[1]['fonts'] | undefined
function loadFonts() {
  fonts ??= [
    { name: 'Fraunces', weight: 500, style: 'normal', data: font('fraunces', 'fraunces-latin-500-normal.woff') },
    { name: 'Fraunces', weight: 400, style: 'italic', data: font('fraunces', 'fraunces-latin-400-italic.woff') },
    {
      name: 'Schibsted Grotesk',
      weight: 400,
      style: 'normal',
      data: font('schibsted-grotesk', 'schibsted-grotesk-latin-400-normal.woff'),
    },
    { name: 'Space Mono', weight: 400, style: 'normal', data: font('space-mono', 'space-mono-latin-400-normal.woff') },
  ]
  return fonts
}

const dataUri = (path: string) => {
  const type = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.svg': 'image/svg+xml' }[
    extname(path).toLowerCase()
  ]
  if (!type) throw new Error(`unsupported card image ${path}`)
  return `data:${type};base64,${readFileSync(path).toString('base64')}`
}

/** A satori node: the shape of a React element, without React. */
interface Node {
  type: string
  props: Record<string, unknown> & { style?: Record<string, unknown>; children?: unknown }
}
const h = (type: string, style: Record<string, unknown>, children?: unknown, props = {}): Node => ({
  type,
  props: { ...props, style: { display: 'flex', ...style }, children },
})

/** The card's layout, in the visual language of og/og-image-v2.html. */
function card(app: CatalogApp): Node {
  const instead = app.replaces?.split(' · ').join(' or ')
  return h(
    'div',
    {
      position: 'relative',
      width: 1200,
      height: 630,
      backgroundColor: '#0b1020',
      backgroundImage: [
        // The icon's glow. A box-shadow would do, but resvg blurs it slowly.
        'radial-gradient(circle at 192px 295px, rgba(37, 99, 235, 0.42), transparent 200px)',
        'radial-gradient(circle at 22% 46%, rgba(37, 99, 235, 0.22), transparent 45%)',
        'radial-gradient(circle at 82% 40%, rgba(124, 91, 255, 0.16), transparent 45%)',
        'radial-gradient(circle at 70% 108%, rgba(236, 72, 153, 0.12), transparent 50%)',
        'linear-gradient(155deg, #070a14 0%, #0b1020 55%, #10162b 100%)',
      ].join(', '),
      fontFamily: 'Schibsted Grotesk',
    },
    [
      h('div', { alignItems: 'center', width: '100%', height: '100%', padding: '0 84px 40px', gap: 60 }, [
        app.icon
          ? h(
              'div',
              {
                flexShrink: 0,
                width: 216,
                height: 216,
                borderRadius: 48,
                overflow: 'hidden',
                backgroundColor: '#ffffff',
              },
              // Icons are drawn edge to edge; a transparent one sits on white.
              h('img', { width: 216, height: 216, objectFit: 'contain' }, undefined, {
                src: dataUri(app.icon),
                width: 216,
                height: 216,
              }),
            )
          : null,
        h('div', { flexDirection: 'column', flex: 1, minWidth: 0 }, [
          app.category
            ? h(
                'div',
                {
                  fontFamily: 'Space Mono',
                  fontSize: 17,
                  letterSpacing: 3,
                  textTransform: 'uppercase',
                  color: '#38bdf8',
                  marginBottom: 22,
                },
                app.category,
              )
            : null,
          h(
            'div',
            { fontFamily: 'Fraunces', fontWeight: 500, fontSize: 96, lineHeight: 1, letterSpacing: -3, color: '#f4f6fb' },
            app.name,
          ),
          app.tagline
            ? h(
                'div',
                {
                  fontFamily: 'Fraunces',
                  fontStyle: 'italic',
                  fontSize: 38,
                  lineHeight: 1.2,
                  marginTop: 24,
                  color: 'transparent',
                  backgroundImage: 'linear-gradient(100deg, #89a9ff 0%, #c9b3ff 50%, #f9a8d4 100%)',
                  backgroundClip: 'text',
                  // Long taglines wrap to at most three lines.
                  lineClamp: 3,
                },
                app.tagline,
              )
            : null,
          instead
            ? h('div', { fontSize: 22, lineHeight: 1.5, marginTop: 26, color: '#a6b0cc' }, `Instead of ${instead}`)
            : null,
        ]),
      ]),
      // Footer: the Freepod mark and domain, bottom right.
      h('div', { position: 'absolute', right: 84, bottom: 40, alignItems: 'center', gap: 14 }, [
        h('img', { width: 36, height: 36 }, undefined, {
          src: dataUri(fileURLToPath(new URL('../public/caelus.svg', import.meta.url))),
          width: 36,
          height: 36,
        }),
        h('div', { fontFamily: 'Space Mono', fontSize: 17, letterSpacing: 1, color: '#8a96b5' }, 'on freepod.eu'),
      ]),
      h('div', {
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 0,
        height: 6,
        backgroundImage: 'linear-gradient(90deg, #2563eb 0%, #7c5bff 50%, #ec4899 100%)',
      }),
    ],
  )
}

/** The app's 1200x630 link-preview card, as PNG. */
export async function renderAppCard(app: CatalogApp): Promise<Buffer> {
  // satori's types want a ReactNode; a plain element-shaped object is what it reads.
  const svg = await satori(card(app) as never, { width: 1200, height: 630, fonts: loadFonts() })
  return new Resvg(svg, { fitTo: { mode: 'original' } }).render().asPng()
}
