import { useRef, useState } from 'react'
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Typography } from '@mui/material'
import ReactCrop, { centerCrop, makeAspectCrop, type PercentCrop } from 'react-image-crop'
import 'react-image-crop/dist/ReactCrop.css'
import { cropImage, SOURCE_MAX_BYTES, type CropOptions } from './cropImage'
import { useObjectUrl } from './useObjectUrl'

interface ImageCropDialogProps extends CropOptions {
  /** The picked file; the dialog is open while it is set. */
  file: File | null
  title: string
  /** Width over height of the crop. */
  aspect: number
  onCancel: () => void
  onChooseAnother: () => void
  onCropped: (blob: Blob) => void
}

function initialCrop(width: number, height: number, aspect: number): PercentCrop {
  return centerCrop(makeAspectCrop({ unit: '%', width: 100 }, aspect, width, height), width, height)
}

/** Lets the owner crop a picked image to `aspect`, then renders it at a size the API accepts. */
export function ImageCropDialog({ file, title, onCancel, ...rest }: ImageCropDialogProps) {
  return (
    <Dialog open={file !== null} onClose={onCancel} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      {file && <CropBody key={`${file.name}:${file.size}:${file.lastModified}`} file={file} onCancel={onCancel} {...rest} />}
    </Dialog>
  )
}

function CropBody({
  file,
  aspect,
  maxEdge,
  maxBytes,
  onCancel,
  onChooseAnother,
  onCropped,
}: Omit<ImageCropDialogProps, 'title' | 'file'> & { file: File }) {
  const imageRef = useRef<HTMLImageElement>(null)
  const tooLarge = file.size > SOURCE_MAX_BYTES
  const url = useObjectUrl(tooLarge ? null : file)
  const [crop, setCrop] = useState<PercentCrop>()
  const [error, setError] = useState<string | null>(
    tooLarge ? `This file is larger than ${SOURCE_MAX_BYTES / (1024 * 1024)} MB. Choose a smaller image.` : null,
  )
  const [busy, setBusy] = useState(false)

  const apply = async () => {
    if (!imageRef.current || !crop) return
    setBusy(true)
    try {
      onCropped(await cropImage(imageRef.current, crop, { maxEdge, maxBytes }))
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  const unreadable = Boolean(error) && !crop

  return (
    <>
      <DialogContent>
        <Stack spacing={2}>
          {error && <Alert severity="error">{error}</Alert>}
          {url && !unreadable && (
            <>
              <Typography variant="body2" color="text.secondary">
                Drag the frame to choose the part to use, and its corners to resize it.
              </Typography>
              <Box sx={{ display: 'flex', justifyContent: 'center', bgcolor: 'action.hover', borderRadius: 1, p: 1 }}>
                <ReactCrop
                  crop={crop}
                  aspect={aspect}
                  keepSelection
                  ruleOfThirds
                  minWidth={16}
                  onChange={(_pixels, percent) => setCrop(percent)}
                >
                  <img
                    ref={imageRef}
                    src={url}
                    alt="The picked image"
                    style={{ maxHeight: '55vh', maxWidth: '100%', display: 'block' }}
                    onLoad={(e) => {
                      const { width, height } = e.currentTarget
                      setCrop(initialCrop(width, height, aspect))
                    }}
                    onError={() =>
                      setError('Your browser cannot read this file. Choose a PNG, JPEG, WebP, GIF or SVG image.')
                    }
                  />
                </ReactCrop>
              </Box>
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>Cancel</Button>
        <Button onClick={onChooseAnother}>Choose another</Button>
        <Button variant="contained" onClick={() => void apply()} disabled={!crop || busy}>
          Use image
        </Button>
      </DialogActions>
    </>
  )
}
