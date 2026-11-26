import {
  Badge,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Tooltip,
} from '@mui/material'
import { ChevronLeft, ChevronRight } from '@mui/icons-material'
import { NavLink, useLocation } from 'react-router-dom'
import { useState, type ReactElement } from 'react'
import type { CSSObject, Theme } from '@mui/material/styles'

export interface SectionNavItem {
  label: string
  path: string
  icon: ReactElement
  /** A count shown on the entry; nothing is shown for 0 or none. */
  badge?: number
}

const DRAWER_WIDTH = 220

const openedMixin = (theme: Theme): CSSObject => ({
  width: DRAWER_WIDTH,
  transition: theme.transitions.create('width', {
    easing: theme.transitions.easing.sharp,
    duration: theme.transitions.duration.enteringScreen,
  }),
  overflowX: 'hidden',
})

const closedMixin = (theme: Theme): CSSObject => ({
  width: `calc(${theme.spacing(7)} + 1px)`,
  transition: theme.transitions.create('width', {
    easing: theme.transitions.easing.sharp,
    duration: theme.transitions.duration.leavingScreen,
  }),
  overflowX: 'hidden',
})

/**
 * Collapsible section nav for a page composed of panels. Extracted from the
 * admin area so account settings reuses that shape rather than growing a
 * second one that drifts from it.
 */
export function SectionSidebar({ items }: { items: SectionNavItem[] }) {
  const location = useLocation()
  const [open, setOpen] = useState(true)

  return (
    <Drawer
      variant="permanent"
      open={open}
      sx={(theme) => ({
        flexShrink: 0,
        whiteSpace: 'nowrap',
        boxSizing: 'border-box',
        ...(open ? openedMixin(theme) : closedMixin(theme)),
        '& .MuiDrawer-paper': {
          position: 'relative',
          ...(open ? openedMixin(theme) : closedMixin(theme)),
        },
      })}
    >
      <List disablePadding>
        {items.map(({ label, path, icon, badge }) => (
          <Tooltip key={path} title={open ? '' : label} placement="right">
            <ListItemButton
              component={NavLink}
              to={path}
              selected={location.pathname.startsWith(path)}
              sx={{
                minHeight: 48,
                px: 2.5,
                justifyContent: open ? 'initial' : 'center',
                '&.Mui-selected': { bgcolor: 'action.selected' },
              }}
            >
              <ListItemIcon
                sx={{ minWidth: 0, mr: open ? 2 : 'auto', justifyContent: 'center' }}
              >
                {badge ? (
                  <Badge
                    color="secondary"
                    badgeContent={badge}
                    max={99}
                    slotProps={{ badge: { 'aria-label': `${badge} unread` } }}
                  >
                    {icon}
                  </Badge>
                ) : (
                  icon
                )}
              </ListItemIcon>
              <ListItemText primary={label} sx={{ opacity: open ? 1 : 0 }} />
            </ListItemButton>
          </Tooltip>
        ))}
      </List>
      <IconButton
        onClick={() => setOpen(!open)}
        aria-label={open ? 'Collapse section navigation' : 'Expand section navigation'}
        sx={{ mx: 'auto', mt: 1 }}
        size="small"
      >
        {open ? <ChevronLeft /> : <ChevronRight />}
      </IconButton>
    </Drawer>
  )
}

export default SectionSidebar
