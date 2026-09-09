import { Button, Card, Stack, Typography } from '@mui/material'

interface ClaimSubdomainBannerProps {
  onChoose: () => void
}

export function ClaimSubdomainBanner({ onChoose }: ClaimSubdomainBannerProps) {
  return (
    <Card sx={{ px: 2.5, py: 1.5 }}>
      <Stack direction="row" spacing={2} alignItems="center" justifyContent="space-between">
        <Typography sx={{ fontSize: 14, color: 'text.secondary' }}>
          You don't have a home domain yet, and you'll need one to deploy.
        </Typography>
        <Button size="small" onClick={onChoose}>
          Claim your free domain name
        </Button>
      </Stack>
    </Card>
  )
}
