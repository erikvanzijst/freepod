import { Box, Stack, Typography } from '@mui/material'
import { fg, line, MONO, SANS } from '../landing/landingTokens'
import type { AppListing } from './listing'
import { listingFacts } from './listingFormat'

/** A definition-list rendering of {@link listingFacts}. */
export function AppFacts({ listing }: { listing: AppListing }) {
  return (
    <Stack divider={<Box sx={{ borderTop: `1px solid ${line.softer}` }} />}>
      {listingFacts(listing).map((fact) => (
        <Stack key={fact.label} direction="row" justifyContent="space-between" sx={{ py: 1.25 }}>
          <Typography sx={{ fontFamily: SANS, fontSize: 14.5, color: fg.faint }}>{fact.label}</Typography>
          <Typography
            sx={{
              fontFamily: fact.label === 'Version' ? MONO : SANS,
              fontSize: 14.5,
              color: fg.primary,
              textAlign: 'right',
            }}
          >
            {fact.value}
          </Typography>
        </Stack>
      ))}
    </Stack>
  )
}

export default AppFacts
