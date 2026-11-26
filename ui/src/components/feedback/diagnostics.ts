/** The page's recent problems, sent along with feedback (feedback-widget, D8). */
export interface DiagnosticEntry {
  at: string
  kind: 'error' | 'rejection' | 'console' | 'api' | 'capture'
  message?: string
  source?: string
  method?: string
  path?: string
  status?: number
}

export const DIAGNOSTICS_LIMIT = 20
const TEXT_LIMIT = 500

let entries: DiagnosticEntry[] = []
let installed = false

function clip(text: string): string {
  return text.length > TEXT_LIMIT ? `${text.slice(0, TEXT_LIMIT - 1)}…` : text
}

function describe(value: unknown): string {
  if (value instanceof Error) return value.stack ? `${value.message}\n${value.stack}` : value.message
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value) ?? String(value)
  } catch {
    return String(value)
  }
}

export function record(entry: Omit<DiagnosticEntry, 'at'>): void {
  const clipped = { ...entry, ...(entry.message ? { message: clip(entry.message) } : {}) }
  entries = [...entries, { at: new Date().toISOString(), ...clipped }].slice(-DIAGNOSTICS_LIMIT)
}

/** A failed platform API call: method, path without its query, and status only. */
export function recordApiFailure(method: string, url: string, status: number | null): void {
  const path = url.split(/[?#]/, 1)[0]
  record({ kind: 'api', method: method.toUpperCase(), path, ...(status === null ? { message: 'network error' } : { status }) })
}

export function snapshot(): DiagnosticEntry[] {
  return [...entries]
}

export function reset(): void {
  entries = []
}

export function installDiagnostics(target: Window = window, sink: Console = console): () => void {
  if (installed) return () => {}
  installed = true
  const onError = (event: ErrorEvent) => {
    record({
      kind: 'error',
      message: event.message || describe(event.error),
      source: event.filename ? `${event.filename}:${event.lineno}:${event.colno}` : undefined,
    })
  }
  const onRejection = (event: PromiseRejectionEvent) => {
    record({ kind: 'rejection', message: describe(event.reason) })
  }
  target.addEventListener('error', onError)
  target.addEventListener('unhandledrejection', onRejection)
  const original = sink.error
  const bound = original.bind(sink)
  sink.error = (...args: unknown[]) => {
    record({ kind: 'console', message: args.map(describe).join(' ') })
    bound(...args)
  }
  return () => {
    target.removeEventListener('error', onError)
    target.removeEventListener('unhandledrejection', onRejection)
    sink.error = original
    installed = false
    entries = []
  }
}
