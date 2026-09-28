/**
 * Markdown source file for each legal document, keyed by URL slug. The build
 * publishes each one verbatim at `/legal/<slug>.md` (see vite.config.ts), so
 * scripts and crawlers can read a document without running the SPA.
 */
export const LEGAL_FILES = {
  terms: 'terms-of-service.md',
  privacy: 'privacy-policy.md',
  aup: 'acceptable-use-policy.md',
  dpa: 'data-processing-agreement.md',
} as const
