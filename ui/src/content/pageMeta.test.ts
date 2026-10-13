import { describe, expect, it } from 'vitest'
import { appPageMeta, renderPageMeta } from './pageMeta'

describe('appPageMeta', () => {
  it('previews an app page with its tagline and card', () => {
    const meta = appPageMeta(
      { slug: 'immich', name: 'Immich', tagline: 'Your photos.', lead: 'Immich is a photo library.' },
      'assets/og-immich-abc.png',
    )
    expect(meta).toEqual({
      path: '/apps/immich',
      file: 'app-immich.html',
      title: 'Immich on Freepod',
      description: 'Immich is a photo library.',
      summary: 'Your photos.',
      image: 'assets/og-immich-abc.png',
    })
    const html = renderPageMeta(meta)
    expect(html).toContain('<meta property="og:url" content="https://freepod.eu/apps/immich" />')
    expect(html).toContain('<meta property="og:image" content="https://freepod.eu/assets/og-immich-abc.png" />')
  })

  it('falls back to a generic line for an app without a tagline', () => {
    const meta = appPageMeta({ slug: 'demo', name: 'Demo & co' }, 'og.png')
    expect(meta.summary).toBe('Demo & co, hosted in Europe on Freepod.')
    expect(meta.description).toBe(meta.summary)
    expect(renderPageMeta(meta)).toContain('<title>Demo &amp; co on Freepod</title>')
  })
})
