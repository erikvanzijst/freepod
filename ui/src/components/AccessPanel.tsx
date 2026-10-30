import { Box, Divider, Typography } from '@mui/material'
import type { Deployment } from '../api/types'
import { formatLocalIso } from '../utils/formatDate'
import { useAccessList } from './access/useAccessList'

/**
 * Who may sign in to a deployment, read-only, for the admin deployment dialog.
 * Renders nothing without Sign in with Freepod; lists entries only when the
 * deployment's access is `listed`.
 */
export function AccessPanel({ deployment }: { deployment: Deployment }) {
  const auth = deployment.auth
  const listed = Boolean(auth?.enabled && auth.access === 'listed')
  const { query } = useAccessList(deployment.user_id, deployment.id, listed)
  if (!auth?.enabled) return null
  const entries = query.data?.entries ?? []

  return (
    <Box>
      <Divider sx={{ my: 2 }} />
      <Typography variant="subtitle2" gutterBottom>
        {listed ? 'Access (only listed people)' : 'Access (any Freepod account)'}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: listed ? 1 : 0 }}>
        auth.protocol: {auth.protocol} · auth.access: {auth.access}
        {listed && ` · ${auth.listed_count ?? entries.length} ${(auth.listed_count ?? entries.length) === 1 ? 'person' : 'people'} besides the owner`}
      </Typography>
      {listed && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          {entries.map((e) => (
            <Box key={e.id} sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
              <Typography variant="body2">{e.email}</Typography>
              <Typography variant="body2" color="text.secondary">
                {e.bound_at ? `signed in ${formatLocalIso(e.bound_at)}` : 'not signed in yet'}
              </Typography>
            </Box>
          ))}
        </Box>
      )}
    </Box>
  )
}
