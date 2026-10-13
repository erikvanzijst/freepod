import { useEffect } from 'react'
import { Box } from '@mui/material'
import { useNavigate } from 'react-router-dom'
import { fg, ink, SANS } from '../components/landing/landingTokens'
import LandingNav from '../components/landing/LandingNav'
import LandingFooter from '../components/landing/LandingFooter'
import EmailDialog from '../components/EmailDialog'
import useStartSignup from '../components/landing/useStartSignup'
import { InstallFlow } from '../components/InstallFlow'
import { useGallery, useGalleryInstall } from '../components/appsgallery/useGallery'
import { RowsLayout } from '../components/appsgallery/RowsLayout'

const navLinks = [
  { label: 'Apps', href: '/apps' },
  { label: 'Pricing', href: '/#pricing' },
  { label: 'Developers', href: '/dev' },
  { label: 'Docs', href: '/docs/' },
]

/** The app catalog at /apps, public whether or not the visitor is signed in. */
export function AppsGallery() {
  const g = useGallery()
  const { start, dialogOpen, setDialogOpen, setEmail, returnTo } = useStartSignup()
  const { install, flow, close } = useGalleryInstall(start)
  const navigate = useNavigate()

  useEffect(() => {
    const previous = document.title
    document.title = 'Apps · Freepod'
    return () => {
      document.title = previous
    }
  }, [])

  return (
    <Box sx={{ background: ink.base, color: fg.primary, fontFamily: SANS, minHeight: '100vh' }}>
      <LandingNav onSignup={start} links={navLinks} />
      <Box component="main">
        <RowsLayout g={g} onInstall={install} />
      </Box>
      <LandingFooter />

      {flow && <InstallFlow product={flow.product} planId={flow.planId} onClose={close} onLaunched={() => navigate('/')} />}

      <EmailDialog
        open={dialogOpen}
        current=""
        onSave={(value) => {
          setEmail(value)
          setDialogOpen(false)
          navigate(returnTo)
        }}
      />
    </Box>
  )
}

export default AppsGallery
