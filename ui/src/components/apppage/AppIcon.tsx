import { Box } from '@mui/material'
import { accentForProduct, DISPLAY } from '../landing/landingTokens'

interface AppIconProps {
  name: string
  src: string | null
  size?: number
}

/** The app's icon on a tinted, rounded tile, sized like a store listing icon. */
export function AppIcon({ name, src, size = 96 }: AppIconProps) {
  const color = accentForProduct(name)
  return (
    <Box
      sx={{
        width: size,
        height: size,
        flex: '0 0 auto',
        borderRadius: `${Math.round(size * 0.26)}px`,
        display: 'grid',
        placeItems: 'center',
        background: `linear-gradient(150deg, rgba(255,255,255,0.96), rgba(238,242,255,0.9))`,
        boxShadow: `0 0 0 1px rgba(255,255,255,0.1), 0 18px 48px ${color}33`,
      }}
    >
      {src ? (
        <Box component="img" src={src} alt="" sx={{ width: '72%', height: '72%', objectFit: 'contain' }} />
      ) : (
        <Box component="span" sx={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: size * 0.45, color }}>{name[0]}</Box>
      )}
    </Box>
  )
}

export default AppIcon
