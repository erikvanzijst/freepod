import { createElement } from 'react'
import { Box, Stack, Typography, type SxProps, type Theme } from '@mui/material'
import type { SvgIconComponent } from '@mui/icons-material'
import SyncRounded from '@mui/icons-material/SyncRounded'
import FaceRetouchingNaturalRounded from '@mui/icons-material/FaceRetouchingNaturalRounded'
import ManageSearchRounded from '@mui/icons-material/ManageSearchRounded'
import PeopleAltRounded from '@mui/icons-material/PeopleAltRounded'
import HistoryRounded from '@mui/icons-material/HistoryRounded'
import PhoneIphoneRounded from '@mui/icons-material/PhoneIphoneRounded'
import HighQualityRounded from '@mui/icons-material/HighQualityRounded'
import AutoAwesomeRounded from '@mui/icons-material/AutoAwesomeRounded'
import AccountTreeRounded from '@mui/icons-material/AccountTreeRounded'
import AlternateEmailRounded from '@mui/icons-material/AlternateEmailRounded'
import AppsRounded from '@mui/icons-material/AppsRounded'
import AttachFileRounded from '@mui/icons-material/AttachFileRounded'
import AutoStoriesRounded from '@mui/icons-material/AutoStoriesRounded'
import CalendarMonthRounded from '@mui/icons-material/CalendarMonthRounded'
import ChatRounded from '@mui/icons-material/ChatRounded'
import CommentRounded from '@mui/icons-material/CommentRounded'
import EditNoteRounded from '@mui/icons-material/EditNoteRounded'
import ForumRounded from '@mui/icons-material/ForumRounded'
import GavelRounded from '@mui/icons-material/GavelRounded'
import GroupsRounded from '@mui/icons-material/GroupsRounded'
import HubRounded from '@mui/icons-material/HubRounded'
import IntegrationInstructionsRounded from '@mui/icons-material/IntegrationInstructionsRounded'
import KeyRounded from '@mui/icons-material/KeyRounded'
import LabelRounded from '@mui/icons-material/LabelRounded'
import LockRounded from '@mui/icons-material/LockRounded'
import MapRounded from '@mui/icons-material/MapRounded'
import PasswordRounded from '@mui/icons-material/PasswordRounded'
import PhotoLibraryRounded from '@mui/icons-material/PhotoLibraryRounded'
import SendRounded from '@mui/icons-material/SendRounded'
import ThumbsUpDownRounded from '@mui/icons-material/ThumbsUpDownRounded'
import { fg } from '../landing/landingTokens'
import type { ListingFeature } from './listing'

const featureIcons: Record<string, SvgIconComponent> = {
  sync: SyncRounded,
  faces: FaceRetouchingNaturalRounded,
  search: ManageSearchRounded,
  share: PeopleAltRounded,
  memories: HistoryRounded,
  mobile: PhoneIphoneRounded,
  original: HighQualityRounded,
  label: LabelRounded,
  map: MapRounded,
  photos: PhotoLibraryRounded,
  comments: CommentRounded,
  history: HistoryRounded,
  apps: AppsRounded,
  autofill: PasswordRounded,
  key: KeyRounded,
  groups: GroupsRounded,
  send: SendRounded,
  lock: LockRounded,
  forum: ForumRounded,
  chat: ChatRounded,
  integrations: IntegrationInstructionsRounded,
  attach: AttachFileRounded,
  federation: HubRounded,
  address: AlternateEmailRounded,
  vote: ThumbsUpDownRounded,
  moderation: GavelRounded,
  library: AutoStoriesRounded,
  edit: EditNoteRounded,
  diagram: AccountTreeRounded,
  calendar: CalendarMonthRounded,
}

export function FeatureIcon({ icon, sx }: { icon: string; sx?: SxProps<Theme> }) {
  return createElement(featureIcons[icon] ?? AutoAwesomeRounded, { sx })
}

/** The app's key features as compact icon bullets, two columns on wide screens. */
export function FeatureList({ features }: { features: ListingFeature[] }) {
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, rowGap: 3, columnGap: 5 }}>
      {features.map((f) => (
        <Stack key={f.title} direction="row" spacing={2}>
          {createElement(featureIcons[f.icon] ?? AutoAwesomeRounded, { sx: { fontSize: 26, color: fg.primary, mt: 0.25 } })}
          <Box>
            <Typography sx={{ fontWeight: 600, fontSize: 16 }}>{f.title}</Typography>
            <Typography sx={{ color: fg.faint, fontSize: 14.5, lineHeight: 1.55 }}>{f.body}</Typography>
          </Box>
        </Stack>
      ))}
    </Box>
  )
}

export default FeatureList
