import type { Deployment } from '../../api/types'

export const ICON_MAX_BYTES = 256 * 1024
export const ICON_TYPES = ['image/png', 'image/jpeg', 'image/webp']

/**
 * The identity Settings edits. `icon` is `undefined` while the owner has not
 * touched it, `null` once they reset it to the product's, and base64 once they
 * picked a file.
 */
export interface IdentityDraft {
  name: string
  description: string
  icon?: string | null
  /** A preview of a picked icon, as a data URL. */
  iconPreview?: string
}

export function identityDraft(d: Deployment): IdentityDraft {
  return { name: d.name, description: d.description ?? '' }
}

/** The identity part of an update: only what changed, leaving managed fields out. */
export function identityPayload(d: Deployment, draft: IdentityDraft) {
  const managed = new Set(d.managed_fields ?? [])
  const payload: { name?: string; description?: string | null; icon?: string | null } = {}
  if (!managed.has('name') && draft.name.trim() !== d.name) payload.name = draft.name
  const description = draft.description.trim() || null
  if (!managed.has('description') && description !== (d.description ?? null)) payload.description = description
  if (!managed.has('icon') && draft.icon !== undefined) payload.icon = draft.icon
  return payload
}

/**
 * The chart values to send: the form's, with every managed key exactly as
 * the deployment has it, so an update never changes one by accident.
 */
export function withManagedValues(d: Deployment, values: Record<string, unknown>): Record<string, unknown> {
  const stored = d.user_values_json ?? {}
  const result = { ...values }
  for (const key of d.managed_fields ?? []) {
    if (key in stored) result[key] = stored[key]
    else delete result[key]
  }
  return result
}

export async function readIcon(file: File): Promise<{ base64: string; preview: string }> {
  if (!ICON_TYPES.includes(file.type)) throw new Error('Choose a PNG, JPEG or WebP image.')
  if (file.size > ICON_MAX_BYTES) throw new Error('Choose an image of at most 256 KiB.')
  const preview = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('Could not read the image.'))
    reader.readAsDataURL(file)
  })
  return { base64: preview.slice(preview.indexOf(',') + 1), preview }
}
