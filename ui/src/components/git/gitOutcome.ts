export type GitOutcome = { severity: 'success' | 'info' | 'error'; message: string }

const ERRORS: Record<string, string> = {
  github_state_invalid: 'That GitHub link was not valid. Try connecting again.',
  github_state_expired: 'That GitHub link has expired. Try connecting again.',
  github_state_other_account:
    'That GitHub sign-in was started from a different Freepod account. Sign in to that account, or start again here.',
  github_code_invalid: 'GitHub did not accept the sign-in. Try connecting again.',
  github_account_in_use: 'That GitHub account is already connected to another Freepod account.',
  github_unavailable: 'GitHub is not available on this Freepod environment.',
}

const FALLBACK = 'Something went wrong talking to GitHub. Try again in a moment.'

export function gitErrorMessage(code: string | undefined): string {
  return (code && ERRORS[code]) || FALLBACK
}

/** What GitHub's return to the Settings page means, from its query string. */
export function gitOutcome(params: URLSearchParams): GitOutcome | null {
  const error = params.get('github_error')
  if (error) return { severity: 'error', message: gitErrorMessage(error) }
  switch (params.get('github')) {
    case 'connected':
      return { severity: 'success', message: 'Your account is connected to GitHub.' }
    case 'requested':
      return {
        severity: 'info',
        message:
          'GitHub asked an owner of that organization to approve the Freepod app. It appears here once they do.',
      }
    case 'canceled':
      return { severity: 'info', message: 'Nothing was changed on GitHub.' }
    default:
      return null
  }
}
