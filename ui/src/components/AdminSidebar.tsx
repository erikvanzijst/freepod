import {
  GroupOutlined,
  InsightsOutlined,
  Inventory2Outlined,
  LocalOfferOutlined,
  RocketLaunchOutlined,
} from '@mui/icons-material'
import { SectionSidebar, type SectionNavItem } from './SectionSidebar'

const navItems: SectionNavItem[] = [
  { label: 'Products', path: '/admin/products', icon: <Inventory2Outlined /> },
  { label: 'Deployments', path: '/admin/deployments', icon: <RocketLaunchOutlined /> },
  { label: 'Users', path: '/admin/users', icon: <GroupOutlined /> },
  { label: 'Plans', path: '/admin/plans', icon: <LocalOfferOutlined /> },
  { label: 'Usage', path: '/admin/usage', icon: <InsightsOutlined /> },
]

export function AdminSidebar() {
  return <SectionSidebar items={navItems} />
}
