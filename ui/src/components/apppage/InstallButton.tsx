import { Button, type ButtonProps } from '@mui/material'
import RocketLaunchRounded from '@mui/icons-material/RocketLaunchRounded'

/** The page's primary call to action. What it starts is still undecided. */
export function InstallButton({ children = 'Install', sx, ...rest }: ButtonProps) {
  return (
    <Button
      variant="contained"
      size="large"
      startIcon={<RocketLaunchRounded />}
      sx={{
        px: 4,
        py: 1.5,
        fontSize: 17,
        color: '#fff',
        background: 'linear-gradient(120deg, #2563EB, #6D5BFF)',
        boxShadow: '0 12px 34px rgba(79,70,229,0.45)',
        '&:hover': { background: 'linear-gradient(120deg, #1d4fd0, #5d4bf0)' },
        ...sx,
      }}
      {...rest}
    >
      {children}
    </Button>
  )
}

export default InstallButton
