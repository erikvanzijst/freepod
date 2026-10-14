/**
 * Per-page link-preview metadata (Open Graph / Twitter cards).
 *
 * Crawlers don't run JavaScript, so these tags must be in the HTML nginx
 * serves for each path. The `pageMeta` Vite plugin renders `/` into
 * index.html and emits one extra HTML file per other path here (`dev.html`
 * for `/dev`) and per catalog app (`app-immich.html` for `/apps/immich`),
 * which nginx maps to that path.
 */

export interface PageMeta {
  /** Served path; also the og:url. */
  path: string
  /** Built HTML file nginx serves for `path`. */
  file: string
  title: string
  /** `<meta name="description">`, for search results. */
  description: string
  /** Shorter card text for og:/twitter:description. */
  summary: string
  /**
   * Path of the card image: under `public/`, rendered from `og/<name>.html` by
   * `og/generate.sh`, or a build asset for an app page (`og/apps.ts`).
   */
  image: string
}

export const SITE_URL = 'https://freepod.eu'

export const PAGE_META: Record<'home' | 'dev', PageMeta> = {
  home: {
    path: '/',
    file: 'index.html',
    title: 'Freepod — Your digital life, in a cloud you control.',
    description:
      'Private alternatives to the cloud services you use every day, for your photos, files, passwords and chats. Each app runs in a pod of its own, hosted in the EU, with no ads or tracking.',
    summary:
      'Private alternatives for your photos, files, passwords and chats, each in a pod of your own. Hosted in the EU.',
    image: 'og-image-v2.png',
  },
  dev: {
    path: '/dev',
    file: 'dev.html',
    title: 'Freepod for developers — Agentic and artisanal hosting.',
    description:
      'Deploy your own apps to the European cloud with one command, by hand or with your coding agent. Any stack, with Postgres, object storage and sign-in built in.',
    summary:
      'Ship your own apps with one command, by hand or with your coding agent. Any stack, Postgres, object storage and sign-in included. Hosted in Europe.',
    image: 'og-image-dev-v2.png',
  },
}

/** The fields of a catalog app that its page's link preview shows. */
export interface AppMetaSource {
  slug: string
  name: string
  tagline?: string
  /** The description's first paragraph. */
  lead?: string
}

/**
 * Link-preview metadata for one catalog app's page at `/apps/<slug>`, served
 * from `app-<slug>.html`. The card text is the tagline, and search results get
 * the description's first paragraph.
 */
export function appPageMeta(app: AppMetaSource, image: string): PageMeta {
  const summary = app.tagline ?? `${app.name}, hosted in Europe on Freepod.`
  return {
    path: `/apps/${app.slug}`,
    file: `app-${app.slug}.html`,
    title: `${app.name} on Freepod`,
    description: app.lead ?? summary,
    summary,
    image,
  }
}

const escape = (value: string) =>
  value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')

/** The `<title>` and preview `<meta>` tags for one page. */
export function renderPageMeta(meta: PageMeta): string {
  const url = `${SITE_URL}${meta.path}`
  const image = `${SITE_URL}/${meta.image}`
  const title = escape(meta.title)
  const summary = escape(meta.summary)
  return [
    `<title>${title}</title>`,
    `<meta name="description" content="${escape(meta.description)}" />`,
    '',
    '<!-- Open Graph (Facebook, LinkedIn, Slack, Discord, iMessage, WhatsApp) -->',
    '<meta property="og:type" content="website" />',
    `<meta property="og:url" content="${url}" />`,
    '<meta property="og:site_name" content="Freepod" />',
    `<meta property="og:title" content="${title}" />`,
    `<meta property="og:description" content="${summary}" />`,
    `<meta property="og:image" content="${image}" />`,
    '<meta property="og:image:width" content="1200" />',
    '<meta property="og:image:height" content="630" />',
    `<meta property="og:image:alt" content="${title}" />`,
    '<meta property="og:locale" content="en_US" />',
    '',
    '<!-- Twitter / X Card -->',
    '<meta name="twitter:card" content="summary_large_image" />',
    `<meta name="twitter:title" content="${title}" />`,
    `<meta name="twitter:description" content="${summary}" />`,
    `<meta name="twitter:image" content="${image}" />`,
    `<meta name="twitter:image:alt" content="${title}" />`,
  ]
    .map((line) => (line ? `    ${line}` : ''))
    .join('\n')
}
