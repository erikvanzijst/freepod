/**
 * Whether `href` is a page of this SPA, to be rendered as a router link.
 *
 * `/docs` is a separate site served by nginx, and a router link would only
 * change the address bar. Router links also don't scroll to a #fragment.
 */
export function isAppRoute(href: string): boolean {
  return (
    href.startsWith('/') &&
    !href.includes('#') &&
    href !== '/docs' &&
    !href.startsWith('/docs/')
  )
}
