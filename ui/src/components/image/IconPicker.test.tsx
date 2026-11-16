import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { IconPicker } from './IconPicker'

const cropImageMock = vi.fn()
vi.mock('./cropImage', async (orig) => ({
  ...(await orig<typeof import('./cropImage')>()),
  cropImage: (...args: unknown[]) => cropImageMock(...args),
}))

URL.createObjectURL = vi.fn(() => 'blob:picked')
URL.revokeObjectURL = vi.fn()

beforeEach(() => {
  cropImageMock.mockResolvedValue(new Blob(['png'], { type: 'image/png' }))
})
afterEach(() => vi.clearAllMocks())

function pick(file: File) {
  fireEvent.change(screen.getByTestId('image-file'), { target: { files: [file] } })
}

describe('IconPicker', () => {
  it('crops a picked image and hands over the result', async () => {
    const onPick = vi.fn()
    render(<IconPicker fallback="A" onPick={onPick} />)
    pick(new File(['x'], 'huge.jpg', { type: 'image/jpeg' }))
    const img = await screen.findByAltText('The picked image')
    Object.defineProperty(img, 'width', { value: 400 })
    Object.defineProperty(img, 'height', { value: 200 })
    fireEvent.load(img)
    fireEvent.click(screen.getByRole('button', { name: 'Use image' }))
    await waitFor(() => expect(onPick).toHaveBeenCalledTimes(1))
    const [file] = onPick.mock.calls[0]
    expect(file).toBeInstanceOf(File)
    expect(file.type).toBe('image/png')
    const [, crop, options] = cropImageMock.mock.calls[0]
    expect(crop).toMatchObject({ unit: '%', width: 50, height: 100, x: 25, y: 0 })
    expect(options).toEqual({ maxEdge: 256, maxBytes: undefined })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('explains a file the browser cannot read, inside the dialog', async () => {
    render(<IconPicker fallback="A" onPick={vi.fn()} />)
    pick(new File(['x'], 'photo.heic', { type: 'image/heic' }))
    fireEvent.error(await screen.findByAltText('The picked image'))
    expect(await screen.findByText(/cannot read this file/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Use image' })).toBeDisabled()
  })

  it('refuses an enormous file before decoding it', async () => {
    render(<IconPicker fallback="A" onPick={vi.fn()} />)
    const file = new File(['x'], 'big.png', { type: 'image/png' })
    Object.defineProperty(file, 'size', { value: 41 * 1024 * 1024 })
    pick(file)
    expect(await screen.findByText(/larger than 40 MB/)).toBeInTheDocument()
    expect(screen.queryByAltText('The picked image')).not.toBeInTheDocument()
  })

  it('shows a refused upload under the icon and offers no edit when read-only', () => {
    const { rerender } = render(<IconPicker fallback="A" onPick={vi.fn()} error="Invalid image file" />)
    expect(screen.getByText('Invalid image file')).toBeInTheDocument()
    rerender(<IconPicker fallback="A" onPick={vi.fn()} readOnly />)
    expect(screen.queryByRole('button', { name: 'Change icon' })).not.toBeInTheDocument()
  })
})
