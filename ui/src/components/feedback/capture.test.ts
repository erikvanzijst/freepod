import { afterEach, describe, expect, it, vi } from 'vitest'
import { captureViewport, keepNode, redactClone } from './capture'
import { reset, snapshot } from './diagnostics'

const domToCanvas = vi.fn()
vi.mock('modern-screenshot', () => ({ domToCanvas: (...args: unknown[]) => domToCanvas(...args) }))

afterEach(() => {
  domToCanvas.mockReset()
  vi.restoreAllMocks()
  reset()
  vi.useRealTimers()
})

describe('capture filter', () => {
  it('leaves out the feedback widget and keeps the page', () => {
    const dialog = document.createElement('div')
    dialog.setAttribute('data-feedback-ui', '')
    expect(keepNode(dialog)).toBe(false)
    expect(keepNode(document.createElement('main'))).toBe(true)
    expect(keepNode(document.createTextNode('hi'))).toBe(true)
  })
})

describe('redaction in the clone', () => {
  it('blanks a password field', () => {
    const input = document.createElement('input')
    input.type = 'password'
    input.value = 'hunter2'
    input.setAttribute('value', 'hunter2')
    redactClone(input)
    expect(input.value).toBe('')
    expect(input.getAttribute('value')).toBe('')
    expect(input.style.getPropertyValue('color')).toBe('transparent')
  })

  it('hides the contents of a marked element but keeps its box', () => {
    const box = document.createElement('div')
    box.setAttribute('data-feedback-redact', '')
    const secret = document.createElement('span')
    secret.textContent = 'postgres://user:pw@db'
    box.appendChild(secret)
    redactClone(box)
    expect(box.style.getPropertyValue('color')).toBe('transparent')
    expect(secret.style.getPropertyValue('visibility')).toBe('hidden')
  })

  it('leaves an ordinary text field alone', () => {
    const input = document.createElement('input')
    input.value = 'my-app'
    redactClone(input)
    expect(input.value).toBe('my-app')
    expect(input.getAttribute('style')).toBeNull()
  })
})

describe('captureViewport', () => {
  it('captures the body and cuts out the viewport as a JPEG', async () => {
    const blob = new Blob(['x'], { type: 'image/jpeg' })
    const drawImage = vi.fn()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage, fillRect: vi.fn(), fillStyle: '' } as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function (cb, type, quality) {
      expect([type, quality]).toEqual(['image/jpeg', 0.8])
      cb(blob)
    })
    vi.spyOn(document.body, 'getBoundingClientRect').mockReturnValue({ left: 0, top: -900, width: 1024 } as DOMRect)
    const full = document.createElement('canvas')
    full.width = 1024
    full.height = 3000
    domToCanvas.mockResolvedValue(full)
    await expect(captureViewport()).resolves.toBe(blob)
    const [node, options] = domToCanvas.mock.calls[0]
    expect(node).toBe(document.body)
    expect(options).toMatchObject({ scale: 1, filter: keepNode, onCloneEachNode: redactClone, style: { margin: '0' } })
    expect(drawImage).toHaveBeenCalledWith(full, -0, 900, window.innerWidth, window.innerHeight, 0, 0, window.innerWidth, window.innerHeight)
  })

  it('resolves to no screenshot and records why when capture fails', async () => {
    domToCanvas.mockRejectedValue(new Error('tainted canvas'))
    await expect(captureViewport()).resolves.toBeNull()
    expect(snapshot()[0]).toMatchObject({ kind: 'capture', message: 'Screenshot failed: tainted canvas' })
  })

  it('gives up after five seconds', async () => {
    vi.useFakeTimers()
    domToCanvas.mockReturnValue(new Promise(() => {}))
    const result = captureViewport()
    await vi.advanceTimersByTimeAsync(5000)
    await expect(result).resolves.toBeNull()
    expect(snapshot()[0].message).toBe('Screenshot timed out')
  })
})
