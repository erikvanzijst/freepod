import { useEffect } from 'react'
import { Box } from '@mui/material'
import { fg, ink, SANS } from '../components/landing/landingTokens'
import LandingNav from '../components/landing/LandingNav'
import LandingFooter from '../components/landing/LandingFooter'
import DevHero from '../components/landing/dev/DevHero'
import DemoSection from '../components/landing/dev/DemoSection'
import FeatureExplorer from '../components/landing/dev/FeatureExplorer'
import EmailDialog from '../components/EmailDialog'
import useStartSignup from '../components/landing/useStartSignup'
import { PAGE_META } from '../content/pageMeta'

const navLinks = [
  { label: 'Demo', href: '#demo' },
  { label: 'Features', href: '#features' },
  { label: 'Docs', href: '/docs/developers' },
  { label: 'Apps', href: '/' },
]

/**
 * Developer landing page at /dev, pitching the `custom` product: deploy your
 * own code with the freepod CLI or a coding agent. Public whether or not the
 * visitor is signed in.
 */
export function DevLanding() {
  const { start, dialogOpen, setDialogOpen, setEmail } = useStartSignup()

  useEffect(() => {
    const previous = document.title
    document.title = PAGE_META.dev.title
    return () => {
      document.title = previous
    }
  }, [])

  return (
    <Box sx={{ background: ink.base, color: fg.primary, fontFamily: SANS, minHeight: '100vh' }}>
      <LandingNav onSignup={start} links={navLinks} />
      <Box component="main">
        <DevHero onSignup={start} />
        <DemoSection />
        <FeatureExplorer />
      </Box>
      <LandingFooter />

      <EmailDialog
        open={dialogOpen}
        current=""
        onSave={(value) => {
          setEmail(value)
          setDialogOpen(false)
        }}
      />
    </Box>
  )
}

export default DevLanding
