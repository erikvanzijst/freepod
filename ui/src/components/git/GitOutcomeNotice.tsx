import { Alert } from '@mui/material'
import { useSearchParams } from 'react-router-dom'
import { gitOutcome } from './gitOutcome'

/** The result GitHub's redirect back carries, until it is dismissed. */
export function GitOutcomeNotice() {
  const [params, setParams] = useSearchParams()
  const outcome = gitOutcome(params)
  if (!outcome) return null
  return (
    <Alert
      severity={outcome.severity}
      variant="outlined"
      onClose={() => setParams({}, { replace: true })}
      sx={{ mb: 2 }}
    >
      {outcome.message}
    </Alert>
  )
}
