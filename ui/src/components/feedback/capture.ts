import { record } from './diagnostics'

/** Marks the widget's own elements, which a screenshot leaves out (D3). */
export const FEEDBACK_UI_ATTR = 'data-feedback-ui'
export const REDACT_ATTR = 'data-feedback-redact'
export const CAPTURE_TIMEOUT_MS = 5000

export function keepNode(node: Node): boolean {
  return !(node instanceof Element && node.hasAttribute(FEEDBACK_UI_ATTR))
}

function blank(el: HTMLElement): void {
  el.style.setProperty('background', '#1b2236', 'important')
  el.style.setProperty('color', 'transparent', 'important')
  el.style.setProperty('caret-color', 'transparent', 'important')
  el.style.setProperty('text-shadow', 'none', 'important')
}

/** D4: secrets are blanked in the clone; the live page is never touched. */
export function redactClone(node: Node): void {
  if (!(node instanceof HTMLElement)) return
  if (node instanceof HTMLInputElement && node.type.toLowerCase() === 'password') {
    node.value = ''
    node.setAttribute('value', '')
    blank(node)
  }
  if (node.hasAttribute(REDACT_ATTR)) {
    blank(node)
    for (const child of Array.from(node.children)) {
      if (child instanceof HTMLElement || child instanceof SVGElement) {
        child.style.setProperty('visibility', 'hidden', 'important')
      }
    }
  }
}

function toJpeg(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.8))
}

/** The part of a capture of the whole body that the viewport showed. */
export function cropToViewport(full: HTMLCanvasElement, body: DOMRect, width: number, height: number): HTMLCanvasElement {
  const ratio = full.width / (body.width || width)
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const g = canvas.getContext('2d')
  if (!g) throw new Error('No 2D canvas')
  g.fillStyle = getComputedStyle(document.body).backgroundColor || '#0B1020'
  g.fillRect(0, 0, width, height)
  g.drawImage(full, -body.left * ratio, -body.top * ratio, width * ratio, height * ratio, 0, 0, width, height)
  return canvas
}

/** The visible part of the page as a JPEG, or null when it cannot be taken.
 * The whole body is rendered and the viewport cut from it: a clone sized to
 * the viewport loses the scroll position. */
export async function captureViewport(): Promise<Blob | null> {
  const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), CAPTURE_TIMEOUT_MS))
  const shot = (async () => {
    const { domToCanvas } = await import('modern-screenshot')
    const body = document.body.getBoundingClientRect()
    const width = window.innerWidth
    const height = window.innerHeight
    const full = await domToCanvas(document.body, {
      scale: 1,
      timeout: CAPTURE_TIMEOUT_MS,
      style: { margin: '0' },
      filter: keepNode,
      onCloneEachNode: redactClone,
    })
    return toJpeg(cropToViewport(full, body, width, height))
  })()
  try {
    const blob = await Promise.race([shot, timeout])
    if (!blob) record({ kind: 'capture', message: 'Screenshot timed out' })
    return blob
  } catch (error) {
    record({ kind: 'capture', message: `Screenshot failed: ${error instanceof Error ? error.message : String(error)}` })
    return null
  }
}
