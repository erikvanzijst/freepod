import { Box } from '@mui/material'
import { fg, ink, SANS } from '../components/landing/landingTokens'
import LandingNav from '../components/landing/LandingNav'
import Hero from '../components/landing/Hero'
import MissionSection from '../components/landing/MissionSection'
import AppShowcase from '../components/landing/AppShowcase'
import HowItWorks from '../components/landing/HowItWorks'
import ValueGrid from '../components/landing/ValueGrid'
import PricingSection from '../components/landing/PricingSection'
import CtaBand from '../components/landing/CtaBand'
import DevelopersBand from '../components/landing/DevelopersBand'
import LandingFooter from '../components/landing/LandingFooter'
import EmailDialog from '../components/EmailDialog'
import useStartSignup from '../components/landing/useStartSignup'

/**
 * Anonymous, conversion-focused landing page shown at the root path when the
 * visitor is not authenticated. In local dev (no oauth2-proxy) the CTA opens
 * the email dialog so you can still enter the app; in production it kicks off
 * the Keycloak sign-in/registration flow.
 */
export function Landing() {
  const { start, dialogOpen, setDialogOpen, setEmail } = useStartSignup()

  return (
    <Box
      sx={{
        background: ink.base,
        color: fg.primary,
        fontFamily: SANS,
        minHeight: '100vh',
      }}
    >
      <LandingNav onSignup={start} />
      <Box component="main">
        <Hero onSignup={start} />
        <MissionSection />
        <AppShowcase />
        <HowItWorks />
        <ValueGrid />
        <PricingSection onSignup={start} />
        <DevelopersBand />
        <CtaBand onSignup={start} />
      </Box>
      <LandingFooter />

      {/* Dev-only path: attach an identity without a real IdP. */}
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

export default Landing
