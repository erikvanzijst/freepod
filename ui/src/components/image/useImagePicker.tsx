import { useRef, useState, type ReactNode } from 'react'
import { ImageCropDialog } from './ImageCropDialog'
import type { CropOptions } from './cropImage'

interface ImagePickerOptions extends CropOptions {
  title: string
  aspect: number
  onPicked: (blob: Blob) => void
}

/**
 * Picks an image and crops it in a dialog. `open()` shows the file chooser;
 * `element` holds the hidden input and the dialog, and must be rendered.
 */
export function useImagePicker({ title, aspect, maxEdge, maxBytes, onPicked }: ImagePickerOptions): {
  open: () => void
  element: ReactNode
} {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const open = () => inputRef.current?.click()

  const element = (
    <>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        hidden
        data-testid="image-file"
        onChange={(e) => {
          const picked = e.target.files?.[0]
          e.target.value = ''
          if (picked) setFile(picked)
        }}
      />
      <ImageCropDialog
        file={file}
        title={title}
        aspect={aspect}
        maxEdge={maxEdge}
        maxBytes={maxBytes}
        onCancel={() => setFile(null)}
        onChooseAnother={open}
        onCropped={(blob) => {
          setFile(null)
          onPicked(blob)
        }}
      />
    </>
  )
  return { open, element }
}
