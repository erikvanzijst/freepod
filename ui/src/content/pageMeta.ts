/**
 * Per-page link-preview metadata (Open Graph / Twitter cards).
 *
 * Crawlers don't run JavaScript, so these tags must be in the HTML nginx
 * serves for each path. The `pageMeta` Vite plugin renders `/` into
 * index.html and emits one extra HTML file per other path here (`dev.html`
 * for `/dev`), which nginx maps to that path.
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
  /** Under `public/`, rendered from `og/<name>.html` by `og/generate.sh`. */
  image: string
}

export const SITE_URL = 'https://freepod.eu'

export const PAGE_META: Record<'home' | 'dev', PageMeta> = {
  home: {
    path: '/',
    file: 'index.html',
    title: 'Freepod — Your digital life, truly yours.',
    description:
      'Freepod runs private, dedicated pods of open-source apps — your photos, files, chat and passwords — hosted in Europe. No ads, no tracking, no lock-in.',
    summary:
      'Private pods running the best open-source apps — photos, files, chat, passwords. Hosted in Europe. No ads, no tracking.',
    image: 'og-image.png',
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
