import '@testing-library/jest-dom'
import { vi } from 'vitest'

// Testing Library's waitFor advances fake timers itself between checks, but it
// only recognizes Jest's API. Pointing that at Vitest's lets a test on fake
// timers wait on its own clock instead of the wall clock.
;(globalThis as Record<string, unknown>).jest = { advanceTimersByTime: (ms: number) => vi.advanceTimersByTime(ms) }
