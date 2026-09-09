import { useCallback, useEffect, useRef, useState } from 'react'
import { Box, CircularProgress, Typography } from '@mui/material'
import CheckIcon from '@mui/icons-material/Check'
import CloseIcon from '@mui/icons-material/Close'
import { checkHostname } from '../../api/endpoints'
import { accent, fg, line, MONO } from '../landing/landingTokens'
import { AppNameReel, type AppNameReelHandle } from './AppNameReel'
import { claimReasonText } from './subdomainReasons'

const DEBOUNCE_MS = 400

export type SubdomainStatus =
  | { status: 'empty' }
  | { status: 'checking' }
  | { status: 'available' }
  | { status: 'refused'; reason: string }

interface SubdomainFieldProps {
  value: string
  onChange: (label: string) => void
  /** The platform domain the label sits under, e.g. `freepod.eu`. */
  domain: string
  onStatusChange?: (status: SubdomainStatus) => void
  /** Select the prefill on mount so typing replaces it. */
  autoSelect?: boolean
  disabled?: boolean
  /**
   * The odometer answers "what goes in front of my domain name?", which is only a
   * live question once the user has an application in mind. Off where they are
   * simply choosing the account's own name.
   */
  showReel?: boolean
  /** Centered where the field is the focus of a page; left where it is a form row. */
  align?: 'start' | 'center'
}

/**
 * The domain name, with only the user's part editable.
 *
 * A bare text field asks for a name whose significance the user cannot see, so
 * the platform domain is always rendered alongside it. With `showReel`, an
 * application label joins them and the whole deployment hostname is on screen.
 *
 * The input is sized to its content rather than filling the row, and the whole
 * control hugs what it holds: a label at one end and its domain at the other do
 * not read as one hostname, which is the only thing this control has to say.
 */
export function SubdomainField({
  value,
  onChange,
  domain,
  onStatusChange,
  autoSelect = false,
  disabled = false,
  showReel = true,
  align = 'start',
}: SubdomainFieldProps) {
  const [state, setState] = useState<SubdomainStatus>({ status: 'empty' })
  const reelRef = useRef<AppNameReelHandle | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const lastStatusRef = useRef<string | null>(null)

  const reducedMotion =
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches

  useEffect(() => {
    onStatusChange?.(state)
  }, [state, onStatusChange])

  useEffect(() => {
    if (!autoSelect) return
    const input = inputRef.current
    if (!input) return
    input.focus()
    input.select()
  }, [autoSelect])

  useEffect(() => {
    if (reducedMotion || !showReel) return
    const timer = setTimeout(() => reelRef.current?.spin(), 450)
    return () => clearTimeout(timer)
  }, [reducedMotion, showReel])

  const settle = useCallback((next: SubdomainStatus) => {
    // Motion as feedback, and only here: the moment a typed label first comes
    // back available. Fired after the debounce, so it never moves under the
    // cursor while somebody is still typing.
    const becameAvailable = next.status === 'available' && lastStatusRef.current !== 'available'
    lastStatusRef.current = next.status
    setState(next)
    if (becameAvailable) reelRef.current?.spin()
  }, [])

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    if (abortRef.current) abortRef.current.abort()

    const label = value.trim().toLowerCase()
    if (!label) {
      lastStatusRef.current = 'empty'
      setState({ status: 'empty' })
      return
    }

    setState({ status: 'checking' })
    const controller = new AbortController()
    abortRef.current = controller

    timerRef.current = setTimeout(async () => {
      try {
        const result = await checkHostname(`${label}.${domain}`)
        if (controller.signal.aborted) return
        settle(result.usable ? { status: 'available' } : { status: 'refused', reason: result.reason ?? 'invalid' })
      } catch {
        if (controller.signal.aborted) return
        settle({ status: 'refused', reason: 'invalid' })
      }
    }, DEBOUNCE_MS)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [value, domain, settle])

  const borderColor =
    state.status === 'available'
      ? 'rgba(52,211,153,0.5)'
      : state.status === 'refused'
        ? 'rgba(248,113,113,0.5)'
        : state.status === 'checking'
          ? 'rgba(91,140,255,0.4)'
          : line.soft

  const message =
    state.status === 'empty'
      ? 'Pick a name to continue.'
      : state.status === 'checking'
        ? 'Checking…'
        : state.status === 'available'
          ? "Available — this one's yours if you want it."
          : claimReasonText(state.reason)

  const messageColor =
    state.status === 'available' ? '#34D399' : state.status === 'refused' ? '#F87171' : fg.faint

  // Monospace, so one character is exactly 1ch: the field is as wide as what is
  // typed, with room for a short name and never wider than its container.
  const inputChars = Math.min(Math.max(value.length, 8), 40)

  return (
    <Box
      sx={{
        width: '100%',
        display: 'flex',
        flexDirection: 'column',
        alignItems: align === 'center' ? 'center' : 'flex-start',
      }}
    >
      <Box
        sx={{
          display: 'inline-flex',
          maxWidth: '100%',
          height: 48,
          alignItems: 'center',
          fontFamily: MONO,
          fontSize: { xs: 13.5, sm: 17 },
          // Both the label and the domain are one line tall and centred by the
          // row, so their baselines cannot drift apart.
          lineHeight: 1,
          border: `1px solid ${borderColor}`,
          borderRadius: '12px',
          background: 'rgba(7,10,20,0.55)',
          overflow: 'hidden',
          transition: 'border-color .18s ease',
        }}
      >
        {showReel && <AppNameReel ref={reelRef} reducedMotion={reducedMotion} />}
        <Box
          component="input"
          ref={inputRef}
          value={value}
          disabled={disabled}
          spellCheck={false}
          autoComplete="off"
          aria-label="Your domain name"
          aria-describedby="subdomain-field-message"
          onChange={(event: React.ChangeEvent<HTMLInputElement>) =>
            onChange(event.target.value.replace(/\./g, ''))
          }
          style={{ width: `${inputChars}ch` }}
          sx={{
            // content-box, so the `ch` width is the text's own and the padding
            // does not eat the last character.
            boxSizing: 'content-box',
            flex: '0 1 auto',
            minWidth: 0,
            border: 0,
            outline: 0,
            background: 'transparent',
            font: 'inherit',
            color: fg.primary,
            pl: 1.25,
            pr: 0,
            textAlign: 'right',
            '&::selection': { background: 'rgba(109,91,255,0.45)' },
          }}
        />
        <Box sx={{ flex: 'none', pr: 1.5, color: fg.faint, whiteSpace: 'nowrap' }}>
          .{domain}
        </Box>
        <Box
          sx={{
            flex: 'none',
            alignSelf: 'stretch',
            width: 44,
            display: 'grid',
            placeItems: 'center',
            borderLeft: `1px solid ${line.softer}`,
          }}
        >
          {state.status === 'checking' && <CircularProgress size={15} />}
          {state.status === 'available' && <CheckIcon sx={{ fontSize: 18, color: '#34D399' }} />}
          {state.status === 'refused' && <CloseIcon sx={{ fontSize: 18, color: '#F87171' }} />}
        </Box>
      </Box>

      <Box
        sx={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: align === 'center' ? 'center' : 'space-between',
          gap: 1.75,
          mt: 1,
          mx: 0.25,
          minHeight: 20,
        }}
      >
        <Typography id="subdomain-field-message" sx={{ fontSize: 13, color: messageColor }}>
          {message}
        </Typography>
        {showReel && !reducedMotion && (
          <Box
            component="button"
            type="button"
            onClick={() => reelRef.current?.spin()}
            sx={{
              fontFamily: MONO,
              fontSize: 11,
              letterSpacing: '0.08em',
              color: fg.faint,
              background: 'none',
              border: 0,
              cursor: 'pointer',
              px: 0.5,
              py: 0.25,
              borderRadius: '6px',
              flex: 'none',
              '&:hover': { color: accent.blue },
            }}
          >
            ↻ again
          </Box>
        )}
      </Box>
    </Box>
  )
}
