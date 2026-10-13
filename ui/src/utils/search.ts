/** True when every word of the query appears in one of the fields, ignoring case. */
export function matchesQuery(fields: (string | null | undefined)[], query: string): boolean {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (terms.length === 0) return true
  const haystack = fields.filter(Boolean).join(' ').toLowerCase()
  return terms.every((term) => haystack.includes(term))
}
