/**
 * What each refusal of a handle claim means, keyed by the platform's stable
 * code. A rejection that only says "invalid" makes the user guess which rule
 * they broke, so every code a claim can return gets its own sentence.
 */
export const CLAIM_REASONS: Record<string, string> = {
  handle_invalid: 'Letters and digits only, 2 to 20 characters.',
  handle_reserved: 'Freepod uses this one itself.',
  handle_taken: 'Taken. Try adding a word or a number.',
}

export function claimReasonText(code: string): string {
  return CLAIM_REASONS[code] ?? 'That handle cannot be used.'
}
