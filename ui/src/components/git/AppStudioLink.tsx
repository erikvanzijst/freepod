import { Link } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'

export function AppStudioLink() {
  return (
    <Link component={RouterLink} to="/apps/appstudio">
      App Studio
    </Link>
  )
}
