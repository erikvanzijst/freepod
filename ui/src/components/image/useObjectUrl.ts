import { useEffect, useMemo, useRef } from 'react'

/**
 * An object URL for `blob`, revoked once it is replaced or unmounted. The
 * revoke is deferred so StrictMode's immediate effect re-run cancels it.
 */
export function useObjectUrl(blob: Blob | null | undefined): string | null {
  const url = useMemo(() => (blob ? URL.createObjectURL(blob) : null), [blob])
  const pending = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (!url) return
    window.clearTimeout(pending.current)
    return () => {
      pending.current = window.setTimeout(() => URL.revokeObjectURL(url), 0)
    }
  }, [url])
  return url
}
