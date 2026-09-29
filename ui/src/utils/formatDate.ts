/**
 * One of the API's timestamps, as an instant. The API serializes naive
 * datetimes that are UTC by construction; `new Date()` would read those as
 * local time and shift every one by the viewer's offset.
 */
export function parseUtc(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)
}

/**
 * Format a date as a local-time ISO-like string: "YYYY-MM-DD HH:MM:SS"
 */
export function formatLocalIso(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const d = value instanceof Date ? value : parseUtc(value)
  if (isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
