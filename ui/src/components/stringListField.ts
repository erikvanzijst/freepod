import type { SchemaField } from './UserValuesForm'

/**
 * A list of strings is edited as text, one entry per line. The form holds the
 * raw text -- so a half-typed empty line survives the next keystroke -- and
 * only the submission splits it; blank lines are dropped there.
 */
export function isStringList(field: Pick<SchemaField, 'type' | 'itemsType'>): boolean {
  return field.type === 'array' && field.itemsType === 'string'
}

export function linesToList(text: unknown): string[] {
  if (Array.isArray(text)) return text.map(String)
  if (typeof text !== 'string') return []
  return text
    .split('\n')
    .map((line) => line.replace(/\r$/, ''))
    .filter((line) => line.trim() !== '')
}
