import type { PercentCrop } from 'react-image-crop'

/** The edge the API stores icons at; a larger upload is only downscaled again. */
export const ICON_EDGE = 256

/** Larger files are refused before decoding, to keep the tab responsive. */
export const SOURCE_MAX_BYTES = 40 * 1024 * 1024

const WEBP_QUALITIES = [0.92, 0.85, 0.75, 0.6]

export interface CropOptions {
  /** The longest edge of the result, in pixels. The crop is never upscaled. */
  maxEdge: number
  /** The largest result to produce. PNG is tried first, then WebP at falling quality. */
  maxBytes?: number
}

function canvasOf(width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  return canvas
}

function context(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Your browser could not process the image.')
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  return ctx
}

function encode(canvas: HTMLCanvasElement, type: string, quality?: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality))
}

/**
 * Draws the cropped part of `image` at its target size. A large reduction is
 * done in halving steps, which a single `drawImage` would render jagged.
 */
function render(image: HTMLImageElement, crop: PercentCrop, maxEdge: number): HTMLCanvasElement {
  const sx = (crop.x / 100) * image.naturalWidth
  const sy = (crop.y / 100) * image.naturalHeight
  const sw = Math.max(1, (crop.width / 100) * image.naturalWidth)
  const sh = Math.max(1, (crop.height / 100) * image.naturalHeight)
  const scale = Math.min(1, maxEdge / Math.max(sw, sh))
  const width = Math.max(1, Math.round(sw * scale))
  const height = Math.max(1, Math.round(sh * scale))

  let source: CanvasImageSource = image
  let rect = { x: sx, y: sy, w: sw, h: sh }
  while (rect.w / 2 > width && rect.h / 2 > height) {
    const step = canvasOf(Math.round(rect.w / 2), Math.round(rect.h / 2))
    context(step).drawImage(source, rect.x, rect.y, rect.w, rect.h, 0, 0, step.width, step.height)
    source = step
    rect = { x: 0, y: 0, w: step.width, h: step.height }
  }
  const out = canvasOf(width, height)
  context(out).drawImage(source, rect.x, rect.y, rect.w, rect.h, 0, 0, width, height)
  return out
}

/** The cropped image as a PNG, or as WebP when the PNG would exceed `maxBytes`. */
export async function cropImage(image: HTMLImageElement, crop: PercentCrop, options: CropOptions): Promise<Blob> {
  const canvas = render(image, crop, options.maxEdge)
  const png = await encode(canvas, 'image/png')
  if (png && (!options.maxBytes || png.size <= options.maxBytes)) return png
  for (const quality of WEBP_QUALITIES) {
    const webp = await encode(canvas, 'image/webp', quality)
    if (webp?.type === 'image/webp' && (!options.maxBytes || webp.size <= options.maxBytes)) return webp
  }
  throw new Error('This image could not be made small enough. Try a smaller crop.')
}

/** A blob as base64, without the data URL prefix, and as a data URL for previews. */
export async function blobToBase64(blob: Blob): Promise<{ base64: string; dataUrl: string }> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('Could not read the image.'))
    reader.readAsDataURL(blob)
  })
  return { base64: dataUrl.slice(dataUrl.indexOf(',') + 1), dataUrl }
}

export function blobToFile(blob: Blob, basename = 'icon'): File {
  const ext = blob.type === 'image/webp' ? 'webp' : 'png'
  return new File([blob], `${basename}.${ext}`, { type: blob.type })
}
