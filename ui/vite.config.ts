/// <reference types="vitest" />
import { readFileSync } from 'node:fs'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { LEGAL_FILES } from './src/content/legal/files'

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

export default defineConfig({
  plugins: [react(), legalMarkdown()],
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
