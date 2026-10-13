import { useEffect } from 'react'
import { Box } from '@mui/material'
import { useNavigate, useParams } from 'react-router-dom'
import { fg, ink, SANS } from '../components/landing/landingTokens'
import LandingNav from '../components/landing/LandingNav'
import LandingFooter from '../components/landing/LandingFooter'
import EmailDialog from '../components/EmailDialog'
import useStartSignup from '../components/landing/useStartSignup'
import { AppListingView } from '../components/apppage/AppListingView'
import { AppNotFound } from '../components/apppage/AppNotFound'
import { useAppListing } from '../components/apppage/useAppListing'
import { useAppInstall } from '../components/apppage/useAppInstall'
import { InstallFlow } from '../components/InstallFlow'
import { useNoIndex } from '../utils/useNoIndex'

const navLinks = [
  { label: 'Apps', href: '/apps' },
  { label: 'Pricing', href: '/#pricing' },
  { label: 'Developers', href: '/dev' },
  { label: 'Docs', href: '/docs/' },
]

/**
 * Public, deep-linkable page for one catalog app at /apps/:slug, reachable
 * signed in or not.
 */
export function AppPage() {
  const { slug } = useParams()
  const { listing, loading, visibility } = useAppListing(slug)
  const { start, dialogOpen, setDialogOpen, setEmail, returnTo } = useStartSignup()
  const navigate = useNavigate()
  const { install, flow, close, launched } = useAppInstall(listing?.id, start)

  const name = listing?.name
  useEffect(() => {
    const previous = document.title
    if (name) document.title = `${name} on Freepod`
    return () => {
      document.title = previous
    }
  }, [name])
  // Only storefront apps belong in search results: not unlisted ones, nor a missing app.
  useNoIndex(visibility ? visibility !== 'public' : !loading)

  return (
    <Box sx={{ background: ink.base, color: fg.primary, fontFamily: SANS, minHeight: '100vh' }}>
      <LandingNav onSignup={start} links={navLinks} />
      <Box component="main">
        {listing && !loading && <AppListingView key={listing.slug} listing={listing} onInstall={install} />}
        {!listing && !loading && <AppNotFound />}
      </Box>
      <LandingFooter />

      {flow && <InstallFlow product={flow.product} planId={flow.planId} onClose={close} onLaunched={launched} />}

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

export default AppPage
