import { Avatar, Badge, CircularProgress, Stack, Typography } from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import { blobToFile, ICON_EDGE } from './cropImage'
import { useImagePicker } from './useImagePicker'

interface IconPickerProps {
  src?: string | null
  /** Shown in place of a missing icon, usually the name's first letter. */
  fallback: string
  alt?: string
  onPick: (file: File) => void
  /** No edit affordance, for an icon the catalog owns. */
  readOnly?: boolean
  busy?: boolean
  /** A refused upload, shown under the icon. */
  error?: string | null
}

/** A product icon that opens the crop dialog when clicked. */
export function IconPicker({ src, fallback, alt, onPick, readOnly, busy, error }: IconPickerProps) {
  const picker = useImagePicker({
    title: 'Crop the icon',
    aspect: 1,
    maxEdge: ICON_EDGE,
    onPicked: (blob) => onPick(blobToFile(blob)),
  })
  const editable = !readOnly && !busy

  return (
    <Stack alignItems="flex-end" spacing={0.5} sx={{ flexShrink: 0, maxWidth: 200 }}>
      {picker.element}
      <Badge
        overlap="circular"
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        badgeContent={
          readOnly ? undefined : busy ? (
            <CircularProgress size={18} />
          ) : (
            <EditIcon
              sx={{ width: 18, height: 18, bgcolor: 'primary.main', color: 'white', borderRadius: '50%', p: 0.3 }}
            />
          )
        }
        sx={{ cursor: editable ? 'pointer' : 'default' }}
        onClick={editable ? picker.open : undefined}
        role={editable ? 'button' : undefined}
        aria-label={editable ? 'Change icon' : undefined}
      >
        <Avatar src={src ?? undefined} alt={alt} variant="rounded" sx={{ width: 64, height: 64, bgcolor: 'action.hover' }}>
          {fallback}
        </Avatar>
      </Badge>
      {error && (
        <Typography variant="caption" color="error" sx={{ textAlign: 'right' }}>
          {error}
        </Typography>
      )}
    </Stack>
  )
}
