// Turns Markdown links to `app:/path` into <AppLink> (a plain <a href="/path">), for
// pages of the Freepod app served next to the docs. A Markdown link to "/path"
// would get the /docs/ baseUrl prepended, and an absolute URL would always
// point at production.
import { visit } from 'unist-util-visit'

const PREFIX = 'app:'

export default function appLinks() {
  return (tree) => {
    visit(tree, 'link', (node, index, parent) => {
      if (!node.url.startsWith(PREFIX) || !parent) return
      parent.children[index] = {
        type: 'mdxJsxTextElement',
        name: 'AppLink',
        attributes: [{ type: 'mdxJsxAttribute', name: 'href', value: node.url.slice(PREFIX.length) }],
        children: node.children,
      }
    })
  }
}
