import { Box, ButtonBase, Dialog, IconButton, Skeleton, Tooltip, Typography } from '@mui/material'
import CloseRoundedIcon from '@mui/icons-material/CloseRounded'
import { useEffect, useMemo, useState } from 'react'
import { fg, line } from '../landing/landingTokens'
import { FEEDBACK_UI_ATTR } from './capture'

interface Props {
  pending: boolean
  image: Blob | null
  onRemove: () => void
}

/** The screenshot that goes with the feedback: a thumbnail that enlarges, and can be removed. */
export function FeedbackScreenshot({ pending, image, onRemove }: Props) {
  const url = useMemo(() => (image ? URL.createObjectURL(image) : null), [image])
  const [enlarged, setEnlarged] = useState(false)

  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url)
  }, [url])

  if (!pending && !url) return null

  return (
    <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5 }}>
      <Box sx={{ position: 'relative', width: 160, flexShrink: 0 }}>
        {pending || !url ? (
          <Skeleton variant="rounded" width={160} height={100} aria-label="Taking a screenshot" />
        ) : (
          <ButtonBase
            onClick={() => setEnlarged(true)}
            aria-label="Enlarge screenshot"
            sx={{ display: 'block', borderRadius: '8px', overflow: 'hidden', border: `1px solid ${line.soft}` }}
          >
            <Box component="img" src={url} alt="Screenshot of the page" sx={{ display: 'block', width: 160 }} />
          </ButtonBase>
        )}
        {!pending && url && (
          <Tooltip title="Remove screenshot">
            <IconButton
              size="small"
              aria-label="Remove screenshot"
              onClick={onRemove}
              sx={{
                position: 'absolute',
                top: 4,
                right: 4,
                bgcolor: 'rgba(7,10,20,0.75)',
                '&:hover': { bgcolor: 'rgba(7,10,20,0.95)' },
              }}
            >
              <CloseRoundedIcon fontSize="inherit" />
            </IconButton>
          </Tooltip>
        )}
      </Box>
      <Typography variant="body2" sx={{ color: fg.muted, pt: 0.5 }}>
        {pending ? 'Taking a screenshot of the page…' : 'A screenshot of the page is included. Remove it if you prefer.'}
      </Typography>
      {url && (
        <Dialog
          open={enlarged}
          onClose={() => setEnlarged(false)}
          maxWidth="lg"
          {...{ [FEEDBACK_UI_ATTR]: '' }}
        >
          <Box
            component="img"
            src={url}
            alt="Screenshot of the page, enlarged"
            onClick={() => setEnlarged(false)}
            sx={{ display: 'block', maxWidth: '100%', maxHeight: '85vh', cursor: 'zoom-out' }}
          />
        </Dialog>
      )}
    </Box>
  )
}

export default FeedbackScreenshot
