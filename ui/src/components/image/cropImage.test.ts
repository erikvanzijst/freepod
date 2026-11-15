import { afterEach, describe, expect, it, vi } from 'vitest'
import { cropImage } from './cropImage'

const drawn: number[][] = []

function stubCanvas(sizes: Record<string, number>) {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (this: HTMLCanvasElement) {
    return { drawImage: (...args: number[]) => drawn.push(args.slice(1)) } as unknown as CanvasRenderingContext2D
  } as never)
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function (this: HTMLCanvasElement, cb, type) {
    const t = type ?? 'image/png'
    cb(new Blob([new Uint8Array(sizes[t] ?? 10)], { type: t }))
  })
}

function image(width: number, height: number): HTMLImageElement {
  const img = document.createElement('img')
  Object.defineProperty(img, 'naturalWidth', { value: width })
  Object.defineProperty(img, 'naturalHeight', { value: height })
  return img
}

const full = { unit: '%' as const, x: 0, y: 0, width: 100, height: 100 }

afterEach(() => {
  vi.restoreAllMocks()
  drawn.length = 0
})

describe('cropImage', () => {
  it('renders the crop at the target edge, in halving steps from a large source', async () => {
    stubCanvas({})
    const blob = await cropImage(image(4000, 4000), full, { maxEdge: 256 })
    expect(blob.type).toBe('image/png')
    const last = drawn[drawn.length - 1]
    expect(last.slice(-2)).toEqual([256, 256])
    expect(drawn.length).toBeGreaterThan(1)
  })

  it('never upscales a small crop', async () => {
    stubCanvas({})
    await cropImage(image(100, 100), { ...full, x: 10, width: 50, height: 50 }, { maxEdge: 256 })
    expect(drawn).toEqual([[10, 0, 50, 50, 0, 0, 50, 50]])
  })

  it('falls back to WebP when the PNG is too large', async () => {
    stubCanvas({ 'image/png': 300_000, 'image/webp': 40_000 })
    const blob = await cropImage(image(256, 256), full, { maxEdge: 256, maxBytes: 256 * 1024 })
    expect(blob.type).toBe('image/webp')
  })

  it('refuses when no encoding fits', async () => {
    stubCanvas({ 'image/png': 300_000, 'image/webp': 300_000 })
    await expect(cropImage(image(256, 256), full, { maxEdge: 256, maxBytes: 1000 })).rejects.toThrow(/small enough/)
  })
})
