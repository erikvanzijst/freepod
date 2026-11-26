import {
  FeedbackOutlined,
  GroupOutlined,
  InsightsOutlined,
  Inventory2Outlined,
  LocalOfferOutlined,
  RocketLaunchOutlined,
} from '@mui/icons-material'
import { useFeedbackUnread } from './feedback/admin/useFeedbackUnread'
import { SectionSidebar, type SectionNavItem } from './SectionSidebar'

export function AdminSidebar() {
  const unread = useFeedbackUnread()
  const navItems: SectionNavItem[] = [
    { label: 'Products', path: '/admin/products', icon: <Inventory2Outlined /> },
    { label: 'Deployments', path: '/admin/deployments', icon: <RocketLaunchOutlined /> },
    { label: 'Users', path: '/admin/users', icon: <GroupOutlined /> },
    { label: 'Plans', path: '/admin/plans', icon: <LocalOfferOutlined /> },
    { label: 'Usage', path: '/admin/usage', icon: <InsightsOutlined /> },
    { label: 'Feedback', path: '/admin/feedback', icon: <FeedbackOutlined />, badge: unread },
  ]
  return <SectionSidebar items={navItems} />
}
