/// <reference types="vitest" />
import { readFileSync } from 'node:fs'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { LEGAL_FILES } from './src/content/legal/files'
import { appPageMeta, PAGE_META, renderPageMeta } from './src/content/pageMeta'
import { readCatalogApps, renderAppCard } from './og/apps'

/** Publishes each legal document's markdown source at /legal/<slug>.md. */
function legalMarkdown(): Plugin {
  return {
    name: 'legal-markdown',
    apply: 'build',
    generateBundle() {
      for (const [slug, file] of Object.entries(LEGAL_FILES)) {
        this.emitFile({
          type: 'asset',
          fileName: `legal/${slug}.md`,
          source: readFileSync(new URL(`./src/content/legal/${file}`, import.meta.url)),
        })
      }
    },
  }
}

/**
 * Renders each page's title and link-preview tags into its own HTML file:
 * `/` into index.html, and a copy of the built index.html per other page
 * (dev.html) and per catalog app (app-<slug>.html, with a card image rendered
 * from the catalog), which nginx serves for that path. Crawlers don't run JS.
 */
function pageMeta(): Plugin {
  const placeholder = '<!--page-meta-->'
  const home = renderPageMeta(PAGE_META.home)
  return {
    name: 'page-meta',
    enforce: 'post',
    transformIndexHtml(html) {
      if (!html.includes(placeholder)) throw new Error(`index.html lacks ${placeholder}`)
      return html.replace(placeholder, home.trimStart())
    },
    async generateBundle(_, bundle) {
      const index = bundle['index.html']
      if (!index || index.type !== 'asset') throw new Error('page-meta: no index.html in the bundle')
      const html = String(index.source)
      if (!html.includes(home.trimStart())) throw new Error('page-meta: built index.html lost its tags')
      const pages = Object.values(PAGE_META).filter((meta) => meta.file !== 'index.html')
      for (const app of readCatalogApps()) {
        // Hashed like any asset, so nginx can cache it as immutable.
        const card = this.emitFile({ type: 'asset', name: `og-${app.slug}.png`, source: await renderAppCard(app) })
        pages.push(appPageMeta(app, this.getFileName(card)))
      }
      for (const meta of pages) {
        this.emitFile({
          type: 'asset',
          fileName: meta.file,
          source: html.replace(home.trimStart(), renderPageMeta(meta).trimStart()),
        })
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), legalMarkdown(), pageMeta()],
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
