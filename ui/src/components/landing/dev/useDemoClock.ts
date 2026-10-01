import { useEffect, useRef, useState } from 'react'

const reducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/**
 * Milliseconds elapsed in a demo of length `total`, advancing only while
 * `running`. Time accumulates per frame (with a clamped delta), so scrolling
 * away or switching tabs pauses the demo rather than skipping ahead. Remount
 * to restart. With reduced motion it sits at the end.
 */
export function useDemoClock(total: number, running: boolean): number {
  const [t, setT] = useState(() => (reducedMotion() ? total : 0))
  const tRef = useRef(t)

  useEffect(() => {
    if (!running || tRef.current >= total) return
    let frame = 0
    let last = performance.now()
    const tick = (now: number) => {
      tRef.current = Math.min(total, tRef.current + Math.min(now - last, 100))
      last = now
      setT(tRef.current)
      if (tRef.current < total) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [running, total])

  return t
}
