import { createElement } from 'react'
import { Box, Stack, Typography, type SxProps, type Theme } from '@mui/material'
import { createSvgIcon } from '@mui/material/utils'
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

// The Git logo mark, from Simple Icons (CC0); Material has no Git icon.
const GitIcon = createSvgIcon(<path d="M23.546 10.93L13.067.452c-.604-.603-1.582-.603-2.188 0L8.708 2.627l2.76 2.76c.645-.215 1.379-.07 1.889.441.516.515.658 1.258.438 1.9l2.658 2.66c.645-.223 1.387-.078 1.9.435.721.72.721 1.884 0 2.604-.719.719-1.881.719-2.6 0-.539-.541-.674-1.337-.404-1.996L12.86 8.955v6.525c.176.086.342.203.488.348.713.721.713 1.883 0 2.6-.719.721-1.889.721-2.609 0-.719-.719-.719-1.879 0-2.598.182-.18.387-.316.605-.406V8.835c-.217-.091-.424-.222-.6-.401-.545-.545-.676-1.342-.396-2.009L7.636 3.7.45 10.881c-.6.605-.6 1.584 0 2.189l10.48 10.477c.604.604 1.582.604 2.186 0l10.43-10.43c.605-.603.605-1.582 0-2.187" />, 'Git')

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
  sparkle: AutoAwesomeRounded,
  git: GitIcon,
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
