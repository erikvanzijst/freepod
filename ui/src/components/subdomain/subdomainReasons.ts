/**
 * What each refusal from the hostname checker means for a label being claimed.
 *
 * A rejection that only says "invalid" makes the user guess which rule they
 * broke, so every reason the checker can return at this depth gets its own
 * sentence. `in_use` is not among them by construction — a deployment is
 * addressed one label further down and cannot contend with a claim — but it is
 * mapped anyway so an unexpected code never renders as a bare string.
 */
export const CLAIM_REASONS: Record<string, string> = {
  invalid: 'Letters, numbers and hyphens only, 2 to 63 characters.',
  reserved: 'Freepod uses this one itself.',
  claimed: 'Taken. Try adding a word or a number.',
  in_use: 'Taken. Try adding a word or a number.',
}

export function claimReasonText(reason: string): string {
  return CLAIM_REASONS[reason] ?? 'That domain name cannot be used.'
}
