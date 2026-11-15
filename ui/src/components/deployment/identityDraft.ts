import type { Deployment } from '../../api/types'

export const ICON_MAX_BYTES = 256 * 1024

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
