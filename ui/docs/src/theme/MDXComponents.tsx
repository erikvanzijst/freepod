import type { ReactNode } from 'react'
import MDXComponents from '@theme-original/MDXComponents'

/** A plain link to a page of the Freepod app; see src/remark/app-links.mjs. */
function AppLink({ href, children }: { href: string; children: ReactNode }) {
  return <a href={href}>{children}</a>
}

export default { ...MDXComponents, AppLink }
