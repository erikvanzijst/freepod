import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Box,
  CircularProgress,
  FormControl,
  FormHelperText,
  InputAdornment,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import { checkHostname } from '../api/endpoints'

const DEBOUNCE_MS = 400

const REASON_LABELS: Record<string, string> = {
  invalid: 'Invalid hostname format',
  reserved: 'Hostname is reserved',
  in_use: 'Already in use',
  claimed: 'That domain name belongs to another account',
}

// Shown when the platform's CNAME target is unknown (endpoint unconfigured).
const DEFAULT_CNAME_TARGET = 'freepod.eu'

type ValidationState =
  | { status: 'idle' }
  | { status: 'checking' }
  | { status: 'valid' }
  | { status: 'error'; reason: string }

interface HostnameFieldProps {
  value: string
  onChange: (hostname: string) => void
  onValidationChange?: (valid: boolean) => void
  /**
   * The account's own domain name, e.g. `erik.freepod.eu`. An application is
   * addressed beneath it, so there is one suffix rather than a list to choose
   * from. Absent only while it is still loading.
   */
  accountFqdn?: string | null
  cnameTarget?: string
  required?: boolean
  error?: string
  description?: string
  initialHostname?: string
  readOnly?: boolean
}

type Mode = 'freepod' | 'custom'

export function HostnameField({ value, onChange, onValidationChange, accountFqdn, cnameTarget, required, error, description, initialHostname, readOnly }: HostnameFieldProps) {
  if (readOnly) {
    return (
      <TextField
        label="Hostname"
        value={value}
        fullWidth
        slotProps={{ input: { readOnly: true } }}
        helperText={description}
      />
    )
  }

  const hasFreepodAddress = Boolean(accountFqdn)
  const [mode, setMode] = useState<Mode>(hasFreepodAddress ? 'freepod' : 'custom')
  const [prefix, setPrefix] = useState('')
  const [customFqdn, setCustomFqdn] = useState('')
  const [validation, setValidation] = useState<ValidationState>({ status: 'idle' })
  const abortRef = useRef<AbortController | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // The account's domain name arrives asynchronously; a value parked in the
  // custom field before it did may turn out to sit beneath it after all.
  const addressInitializedRef = useRef(hasFreepodAddress)
  useEffect(() => {
    if (addressInitializedRef.current || !accountFqdn) return
    addressInitializedRef.current = true

    if (customFqdn && customFqdn.endsWith(`.${accountFqdn}`)) {
      setPrefix(customFqdn.slice(0, -(accountFqdn.length + 1)))
      setCustomFqdn('')
    }
    setMode('freepod')
  }, [accountFqdn, customFqdn])

  // Sync initial value into local state on mount
  const initializedRef = useRef(false)
  useEffect(() => {
    if (initializedRef.current || !value) return
    initializedRef.current = true

    if (accountFqdn && value.endsWith(`.${accountFqdn}`)) {
      setPrefix(value.slice(0, -(accountFqdn.length + 1)))
      setMode('freepod')
      return
    }
    setCustomFqdn(value)
    setMode('custom')
  }, [value, accountFqdn])

  const currentFqdn =
    mode === 'freepod' ? (prefix ? `${prefix}.${accountFqdn}` : '') : customFqdn

  const validate = useCallback((fqdn: string) => {
    if (timerRef.current) clearTimeout(timerRef.current)
    if (abortRef.current) abortRef.current.abort()

    if (!fqdn) {
      setValidation({ status: 'idle' })
      return
    }

    // Skip API check when hostname matches the initial value (edit mode)
    if (initialHostname && fqdn === initialHostname) {
      setValidation({ status: 'valid' })
      return
    }

    setValidation({ status: 'checking' })
    const controller = new AbortController()
    abortRef.current = controller

    timerRef.current = setTimeout(async () => {
      try {
        const result = await checkHostname(fqdn)
        if (controller.signal.aborted) return
        if (result.usable) {
          setValidation({ status: 'valid' })
        } else {
          setValidation({ status: 'error', reason: result.reason ?? 'invalid' })
        }
      } catch {
        if (controller.signal.aborted) return
        setValidation({ status: 'error', reason: 'invalid' })
      }
    }, DEBOUNCE_MS)
  }, [initialHostname])

  // Trigger validation and propagate value when the computed FQDN changes
  const prevFqdnRef = useRef(currentFqdn)
  useEffect(() => {
    if (prevFqdnRef.current === currentFqdn) return
    prevFqdnRef.current = currentFqdn
    onChange(currentFqdn)
    validate(currentFqdn)
  }, [currentFqdn, onChange, validate])

  // Notify parent of validation state changes
  useEffect(() => {
    onValidationChange?.(validation.status === 'valid')
  }, [validation.status, onValidationChange])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      if (abortRef.current) abortRef.current.abort()
    }
  }, [])

  const handleModeChange = (_: unknown, newMode: Mode | null) => {
    if (!newMode) return
    setMode(newMode)
    setValidation({ status: 'idle' })
    if (newMode === 'freepod') {
      setCustomFqdn('')
    } else {
      setPrefix('')
    }
  }

  // The CNAME target differs per environment (e.g. dev.freepod.eu vs freepod.eu),
  // so the not_resolving message is built from the backend-provided value.
  const cnameDomain = cnameTarget || DEFAULT_CNAME_TARGET
  const reasonLabel = (reason: string) =>
    reason === 'not_resolving'
      ? `Create a CNAME record pointing to ${cnameDomain}`
      : REASON_LABELS[reason] ?? reason

  const statusIcon = (() => {
    switch (validation.status) {
      case 'checking':
        return <CircularProgress size={20} />
      case 'valid':
        return <CheckCircleIcon color="success" />
      case 'error':
        return (
          <Tooltip title={reasonLabel(validation.reason)}>
            <ErrorIcon color="error" />
          </Tooltip>
        )
      default:
        return null
    }
  })()

  const helperText =
    error ??
    (validation.status === 'error' ? reasonLabel(validation.reason) : undefined) ??
    description

  const modeToggle = hasFreepodAddress ? (
    <ToggleButtonGroup
      value={mode}
      exclusive
      onChange={handleModeChange}
      size="small"
      sx={{ alignSelf: 'flex-end' }}
    >
      <ToggleButton value="freepod" sx={{ whiteSpace: 'nowrap' }}>
        <Typography variant="caption">Free domain</Typography>
      </ToggleButton>
      <ToggleButton value="custom" sx={{ whiteSpace: 'nowrap' }}>
        <Typography variant="caption">Custom domain</Typography>
      </ToggleButton>
    </ToggleButtonGroup>
  ) : null

  return (
    <FormControl fullWidth error={!!error || validation.status === 'error'}>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
        {modeToggle}
        {mode === 'freepod' ? (
          <TextField
            label="Hostname"
            value={prefix}
            onChange={(e) => setPrefix(e.target.value.replace(/\./g, ''))}
            required={required}
            error={!!error || validation.status === 'error'}
            slotProps={{
              // Right-aligned, so the label stays against its domain: the two
              // only read as one hostname while nothing sits between them.
              htmlInput: { style: { textAlign: 'right', paddingRight: 0 } },
              input: {
                endAdornment: (
                  <InputAdornment position="end">
                    <Typography sx={{ color: 'text.secondary', mr: 1, whiteSpace: 'nowrap' }}>
                      .{accountFqdn}
                    </Typography>
                    {statusIcon}
                  </InputAdornment>
                ),
              },
            }}
            fullWidth
          />
        ) : (
          <>
            <TextField
              label="Hostname"
              value={customFqdn}
              onChange={(e) => setCustomFqdn(e.target.value)}
              placeholder="myapp.example.com"
              required={required}
              error={!!error || validation.status === 'error'}
              slotProps={{
                input: { endAdornment: <InputAdornment position="end">{statusIcon}</InputAdornment> },
              }}
              fullWidth
            />
            <Typography variant="caption" color="text.secondary">
              Point your domain at Freepod: create a CNAME record → {cnameDomain}
            </Typography>
          </>
        )}
      </Box>

      {helperText && <FormHelperText>{helperText}</FormHelperText>}
    </FormControl>
  )
}
