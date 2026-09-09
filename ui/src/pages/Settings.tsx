import { Box } from '@mui/material'
import { Outlet } from 'react-router-dom'
import LanguageOutlinedIcon from '@mui/icons-material/LanguageOutlined'
import VpnKeyOutlinedIcon from '@mui/icons-material/VpnKeyOutlined'
import { PageHeading } from '../components/PageHeading'
import { SectionSidebar, type SectionNavItem } from '../components/SectionSidebar'

/**
 * Account settings. Composed of panels behind a section nav, the same shape the
 * admin area uses, so further account-level sections drop in beside SSH keys
 * without reworking the page.
 */
const navItems: SectionNavItem[] = [
  { label: 'Domain name', path: '/settings/domain', icon: <LanguageOutlinedIcon /> },
  { label: 'SSH keys', path: '/settings/ssh-keys', icon: <VpnKeyOutlinedIcon /> },
]

function Settings() {
  return (
    <Box>
      <Box sx={{ mb: 3 }}>
        <PageHeading
          eyebrow="Your account"
          title="Settings"
          subtitle="How you identify yourself to the platform."
        />
      </Box>
      <Box sx={{ display: 'flex', gap: 3 }}>
        <SectionSidebar items={navItems} />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Outlet />
        </Box>
      </Box>
    </Box>
  )
}

export default Settings
