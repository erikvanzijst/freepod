/**
 * The two Section 1 demos, as timeline scripts. Output is condensed and
 * sanitized: a real build streams hundreds of lines nobody needs to see here.
 */
import type { Seg, Step } from './timeline'

export type DemoId = 'agent' | 'manual'

export interface Demo {
  id: DemoId
  windowTitle: string
  steps: Step[]
  url: string
  /** Renders as an agent TUI (input box + status footer) rather than a shell. */
  tui?: boolean
}

const blank: Step = { kind: 'out', segs: [['\u00a0']], delay: 60 }
const tool = (name: string): Seg[] => [['● ', 'accent'], [name.padEnd(7), 'fg']]

export const manualDemo: Demo = {
  id: 'manual',
  windowTitle: '~/hello — zsh',
  url: 'hello.ada.freepod.eu',
  steps: [
    { kind: 'wait', ms: 500 },
    { kind: 'cmd', text: 'npm init -y > /dev/null' },
    { kind: 'cmd', text: 'cat > index.js' },
    { kind: 'type', text: "require('http').createServer((req, res) => {" },
    { kind: 'type', text: "  res.end('Hello, world!\\n')" },
    { kind: 'type', text: '}).listen(process.env.PORT)' },
    { kind: 'out', segs: [['^D', 'dim']], delay: 260 },
    { kind: 'cmd', text: 'freepod init', pause: 500 },
    { kind: 'type', text: '', prefix: [['  hostname ', 'muted'], ['[hello]', 'dim'], [': ', 'muted']], pause: 700 },
    { kind: 'out', segs: [['  → ', 'dim'], ['hello.ada.freepod.eu', 'fg']] },
    { kind: 'out', segs: [['~/hello/.freepod.json', 'muted']], delay: 220 },
    { kind: 'cmd', text: 'freepod deploy', pause: 450 },
    {
      kind: 'task',
      segs: [['Packing and uploading', 'muted']],
      ms: 700,
      done: [['✓ ', 'ok'], ['Uploaded   ', 'fg'], ['2 files · 436 B', 'dim']],
    },
    {
      kind: 'task',
      segs: [['Building   ', 'muted'], ['detected Node.js 22', 'dim']],
      ms: 2600,
      done: [['✓ ', 'ok'], ['Built      ', 'fg'], ['node index.js · 38s', 'dim']],
    },
    {
      kind: 'task',
      segs: [['Releasing', 'muted']],
      ms: 1300,
      done: [['✓ ', 'ok'], ['Released   ', 'fg'], ['TLS certificate issued', 'dim']],
    },
    { kind: 'out', segs: [['https://hello.ada.freepod.eu', 'link']], delay: 260 },
    { kind: 'cmd', text: '', pause: 0 },
  ],
}

export const agentDemo: Demo = {
  id: 'agent',
  windowTitle: '~/links — agent',
  url: 'links.ada.freepod.eu',
  tui: true,
  steps: [
    { kind: 'wait', ms: 600 },
    { kind: 'prompt', text: 'Create a link shortener and deploy it to freepod' },
    { kind: 'mark', name: 'work-start' },
    blank,
    {
      kind: 'task',
      segs: [...tool('Skill'), ['deploy-to-freepod', 'muted']],
      ms: 800,
      done: [...tool('Skill'), ['deploy-to-freepod', 'muted'], ['  loaded', 'dim']],
    },
    { kind: 'out', segs: [['  Node + Express, links stored in Postgres via DATABASE_URL.', 'dim']], delay: 300 },
    {
      kind: 'task',
      segs: [...tool('Write'), ['server.js', 'muted']],
      ms: 1100,
      done: [...tool('Write'), ['package.json  server.js  public/index.html', 'muted'], ['  +118', 'ok']],
    },
    {
      kind: 'task',
      segs: [...tool('Bash'), ['npm test', 'muted']],
      ms: 1200,
      done: [...tool('Bash'), ['npm test', 'muted'], ['  ✓ 6 passed', 'ok']],
    },
    {
      kind: 'task',
      segs: [...tool('Bash'), ['freepod init', 'muted']],
      ms: 700,
      done: [...tool('Bash'), ['freepod init', 'muted'], ['  → links.ada.freepod.eu', 'dim']],
    },
    {
      kind: 'task',
      segs: [...tool('Bash'), ['freepod deploy', 'muted']],
      ms: 2900,
      done: [...tool('Bash'), ['freepod deploy', 'muted'], ['  ✓ built · released in 52s', 'ok']],
    },
    blank,
    { kind: 'out', segs: [['  Your link shortener is live:', 'fg']], delay: 300 },
    { kind: 'out', segs: [['  '], ['https://links.ada.freepod.eu', 'link']], delay: 120 },
    { kind: 'mark', name: 'work-end' },
    { kind: 'wait', ms: 400 },
  ],
}

export const demos: Record<DemoId, Demo> = { agent: agentDemo, manual: manualDemo }
