export const SUPPORT_EMAIL = 'support@freepod.eu'

/** A mailto link to support, prefilled with a subject and body. */
export function supportMailto(subject: string, body: string): string {
  return `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
}
