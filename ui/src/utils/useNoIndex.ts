import { useEffect } from 'react'

/** Ask search engines not to index the current page while `active`. */
export function useNoIndex(active: boolean) {
  useEffect(() => {
    if (!active) return
    const tag = document.createElement('meta')
    tag.name = 'robots'
    tag.content = 'noindex'
    document.head.appendChild(tag)
    return () => tag.remove()
  }, [active])
}
