import { describe, expect, it } from 'vitest'
import indexHtml from '../../index.html?raw'
import llmsTxt from '../../public/llms.txt?raw'

describe.each([
  ['index.html', indexHtml],
  ['llms.txt', llmsTxt],
])('static instructions in %s', (_, content) => {
  it.each([
    'uv tool install freepod',
    'freepod skill install',
    'freepod login',
    'freepod deploy',
    'https://freepod.eu/dev',
    'https://freepod.eu/docs/developers/coding-agents',
  ])('mention %s', (text) => {
    expect(content).toContain(text)
  })
})
