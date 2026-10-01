/**
 * A tiny, deterministic timeline for the fake terminal demos.
 *
 * A demo is a list of steps (typed commands, output lines, spinner tasks). It
 * compiles to timestamped lines once, and the renderer derives everything it
 * shows from a single clock value, so restarting, jumping to the end
 * (reduced motion) and pausing all fall out for free.
 */

export type Tone = 'fg' | 'muted' | 'dim' | 'ok' | 'link' | 'prompt' | 'accent' | 'warn'
export type Seg = [text: string, tone?: Tone]

export type Step =
  /** A shell command typed at the prompt, followed by a pause for Enter. */
  | { kind: 'cmd'; text: string; prompt?: Seg[]; speed?: number; pause?: number }
  /** A line typed without the shell prompt (heredoc body, a prompt answer). */
  | { kind: 'type'; text: string; prefix?: Seg[]; tone?: Tone; speed?: number; pause?: number }
  /** An output line, appearing after `delay` ms. */
  | { kind: 'out'; segs: Seg[]; delay?: number }
  /** A spinner line that resolves into `done` after `ms`. */
  | { kind: 'task'; segs: Seg[]; ms: number; done: Seg[] }
  /** The agent TUI's input box: typed there, then submitted into the history. */
  | { kind: 'prompt'; text: string; speed?: number }
  | { kind: 'wait'; ms: number }
  /** Records the current time under `name` (e.g. the agent's working window). */
  | { kind: 'mark'; name: string }

export interface Line {
  start: number
  prefix: Seg[]
  segs?: Seg[]
  typed?: { text: string; tone?: Tone; end: number }
  task?: { until: number; done: Seg[] }
}

export interface Compiled {
  lines: Line[]
  total: number
  marks: Record<string, number>
  input?: { start: number; end: number; text: string }
}

export const SHELL_PROMPT: Seg[] = [['~/hello', 'accent'], [' $ ', 'dim']]

export function compile(steps: Step[]): Compiled {
  const lines: Line[] = []
  const marks: Record<string, number> = {}
  let input: Compiled['input']
  let t = 0

  for (const step of steps) {
    switch (step.kind) {
      case 'cmd': {
        const end = t + step.text.length * (step.speed ?? 55)
        lines.push({ start: t, prefix: step.prompt ?? SHELL_PROMPT, typed: { text: step.text, end } })
        t = end + (step.pause ?? 420)
        break
      }
      case 'type': {
        const end = t + step.text.length * (step.speed ?? 24)
        lines.push({ start: t, prefix: step.prefix ?? [], typed: { text: step.text, tone: step.tone, end } })
        t = end + (step.pause ?? 140)
        break
      }
      case 'out':
        t += step.delay ?? 110
        lines.push({ start: t, prefix: [], segs: step.segs })
        break
      case 'task':
        t += 160
        lines.push({ start: t, prefix: [], segs: step.segs, task: { until: t + step.ms, done: step.done } })
        t += step.ms
        break
      case 'prompt': {
        const end = t + step.text.length * (step.speed ?? 42)
        input = { start: t, end, text: step.text }
        t = end + 520
        lines.push({ start: t, prefix: [['❯ ', 'prompt']], segs: [[step.text, 'fg']] })
        break
      }
      case 'wait':
        t += step.ms
        break
      case 'mark':
        marks[step.name] = t
        break
    }
  }

  return { lines, total: t, marks, input }
}

/** Characters of a typed span visible at time `t`. */
export function typedLength(text: string, start: number, end: number, t: number): number {
  if (t >= end) return text.length
  if (t <= start) return 0
  return Math.floor(((t - start) / (end - start)) * text.length)
}

const SPINNER = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'

export function spinnerFrame(t: number): string {
  return SPINNER[Math.floor(t / 80) % SPINNER.length]
}
