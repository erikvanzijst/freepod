import { Box, Container, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { accent, DISPLAY, fg } from '../landing/landingTokens'
import { AppSearch } from './CatalogBar'

/** Shown for an /apps/:slug that matches no visible product. */
export function AppNotFound() {
  return (
    <Container maxWidth="sm" sx={{ py: { xs: 10, md: 16 }, textAlign: 'center' }}>
      <Typography component="h1" sx={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: { xs: 34, md: 44 } }}>
        We couldn’t find that app
      </Typography>
      <Typography sx={{ mt: 2, color: fg.muted, fontSize: 17 }}>
        Search for it below, or{' '}
        <Box component={RouterLink} to="/apps" sx={{ color: accent.blue }}>browse all apps</Box>.
      </Typography>
      <Box sx={{ mt: 4, display: 'flex', justifyContent: 'center' }}>
        <AppSearch width="100%" />
      </Box>
    </Container>
  )
}

export default AppNotFound
