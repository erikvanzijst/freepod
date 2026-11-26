const SECRET_KEY = /^(code|state|token|.*_token|.*secret)$/i

/** The page as a same-site path and query without fragment or secret-looking
 * parameters (D7); the API applies the same rule authoritatively. */
export function cleanPage(page: string): string {
  const [path, query = ''] = page.split('#', 1)[0].split(/\?(.*)/s, 2)
  const kept = query
    .split('&')
    .filter((pair) => {
      if (!pair) return false
      const key = pair.split('=', 1)[0]
      let decoded = key
      try {
        decoded = decodeURIComponent(key.replace(/\+/g, ' '))
      } catch {
        // keep the raw key
      }
      return !SECRET_KEY.test(decoded)
    })
  return kept.length ? `${path}?${kept.join('&')}` : path
}

export function isSitePath(value: string | null | undefined): value is string {
  return Boolean(value && value.startsWith('/') && !value.startsWith('//') && !value.includes('\\'))
}

/** Which page a feedback link names: `from`, else a same-origin referrer, else `/`. */
export function linkedPage(from: string | null, referrer: string, origin: string): string {
  if (isSitePath(from)) return cleanPage(from)
  if (referrer) {
    try {
      const url = new URL(referrer)
      if (url.origin === origin) return cleanPage(url.pathname + url.search)
    } catch {
      // not a URL
    }
  }
  return '/'
}
