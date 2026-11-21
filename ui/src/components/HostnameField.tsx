import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Box,
  CircularProgress,
  FormControl,
  FormHelperText,
  InputAdornment,
  Link,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CloudDoneIcon from '@mui/icons-material/CloudDone'
import ErrorIcon from '@mui/icons-material/Error'
import { checkHostname } from '../api/endpoints'
import type { OwnershipRecord } from '../api/types'

const DEBOUNCE_MS = 400

// The prefilled name, then `-2` and `-3`, before it is left for the user.
const MAX_AUTO_TRIES = 3

const REASON_LABELS: Record<string, string> = {
  invalid: 'Invalid hostname format',
  reserved: 'Hostname is reserved',
  in_use: 'Already in use',
  claimed: 'That address belongs to another account',
}

// Shown when the platform's CNAME target is unknown (endpoint unconfigured).
const DEFAULT_CNAME_TARGET = 'freepod.app'

const SETUP_GUIDE = '/docs/apps/managing/custom-domain'
const CLOUDFLARE_GUIDE = `${SETUP_GUIDE}#through-cloudflares-proxy`

type ValidationState =
  | { status: 'idle' }
  | { status: 'checking' }
  | { status: 'valid'; proxy?: string | null }
  | { status: 'error'; reason: string; record?: OwnershipRecord | null }

interface HostnameFieldProps {
  value: string
  onChange: (hostname: string) => void
  onValidationChange?: (valid: boolean) => void
  /**
   * The text that follows an application label in this account's hostnames,
   * as the platform reports it (e.g. `-erik.freepod.app`). Opaque: it is
   * appended to the label, never taken apart. Absent only while loading.
   */
  suffix?: string | null
  cnameTarget?: string
  required?: boolean
  error?: string
  description?: string
  initialHostname?: string
  readOnly?: boolean
  /** Prefills an empty field's label; while untouched, a refused one is retried with a numeric suffix. */
  defaultPrefix?: string
}

type Mode = 'freepod' | 'custom'

export function HostnameField({ value, onChange, onValidationChange, suffix, cnameTarget, required, error, description, initialHostname, readOnly, defaultPrefix }: HostnameFieldProps) {
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

  const hasFreepodAddress = Boolean(suffix)
  const [mode, setMode] = useState<Mode>(hasFreepodAddress ? 'freepod' : 'custom')
  const [prefix, setPrefix] = useState('')
  const [customFqdn, setCustomFqdn] = useState('')
  const [validation, setValidation] = useState<ValidationState>({ status: 'idle' })
  const abortRef = useRef<AbortController | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // The prefilled name and how many candidates have been tried, until the
  // user edits the field: a name someone chose is never silently replaced.
  const autoNameRef = useRef<{ base: string; tries: number } | null>(null)

  // The account's suffix arrives asynchronously; a value parked in the custom
  // field before it did may turn out to be a Freepod address after all.
  const addressInitializedRef = useRef(hasFreepodAddress)
  useEffect(() => {
    if (addressInitializedRef.current || !suffix) return
    addressInitializedRef.current = true

    if (customFqdn && customFqdn.endsWith(suffix)) {
      setPrefix(customFqdn.slice(0, -suffix.length))
      setCustomFqdn('')
    }
    setMode('freepod')
  }, [suffix, customFqdn])

  // Sync initial value into local state on mount, or with none, prefill the
  // default name once the account's suffix is known.
  const initializedRef = useRef(false)
  useEffect(() => {
    if (initializedRef.current) return
    if (!value) {
      if (!defaultPrefix || !suffix) return
      initializedRef.current = true
      autoNameRef.current = { base: defaultPrefix, tries: 1 }
      setPrefix(defaultPrefix)
      setMode('freepod')
      return
    }
    initializedRef.current = true

    if (suffix && value.endsWith(suffix) && value.length > suffix.length) {
      setPrefix(value.slice(0, -suffix.length))
      setMode('freepod')
      return
    }
    setCustomFqdn(value)
    setMode('custom')
  }, [value, suffix, defaultPrefix])

  const currentFqdn =
    mode === 'freepod' ? (prefix ? `${prefix}${suffix}` : '') : customFqdn

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
          setValidation({ status: 'valid', proxy: result.proxy })
          return
        }
        const auto = autoNameRef.current
        if (auto && auto.tries < MAX_AUTO_TRIES) {
          setPrefix(`${auto.base}-${++auto.tries}`)
          return
        }
        setValidation({ status: 'error', reason: result.reason ?? 'invalid', record: result.ownership_record })
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
    autoNameRef.current = null
    setMode(newMode)
    setValidation({ status: 'idle' })
    if (newMode === 'freepod') {
      setCustomFqdn('')
    } else {
      setPrefix('')
    }
  }

  // The platform domain differs per environment (e.g. dev.freepod.eu vs freepod.eu),
  // so the not_resolving message is built from the backend-provided value.
  const cnameDomain = cnameTarget || DEFAULT_CNAME_TARGET
  const reasonLabel = (reason: string, record?: OwnershipRecord | null) => {
    if (reason === 'not_resolving') return `Not pointing at ${cnameDomain} yet`
    if (reason === 'ownership_unverified')
      return record
        ? `Cloudflare proxy: add TXT ${record.name} = ${record.value}`
        : 'Cloudflare proxy: a TXT record must show you own the domain'
    return REASON_LABELS[reason] ?? reason
  }
  const proxiedLabel = 'Cloudflare proxy, unverified: use SSL/TLS Full (strict), Always Use HTTPS off'
  const proxied =
    (validation.status === 'valid' && !!validation.proxy) ||
    (validation.status === 'error' && validation.reason === 'ownership_unverified')

  const statusIcon = (() => {
    switch (validation.status) {
      case 'checking':
        return <CircularProgress size={20} />
      case 'valid':
        return validation.proxy ? (
          <Tooltip title={proxiedLabel}>
            <CloudDoneIcon color="warning" />
          </Tooltip>
        ) : (
          <CheckCircleIcon color="success" />
        )
      case 'error':
        return (
          <Tooltip title={reasonLabel(validation.reason, validation.record)}>
            <ErrorIcon color="error" />
          </Tooltip>
        )
      default:
        return null
    }
  })()

  const helperText =
    error ??
    (validation.status === 'error' ? reasonLabel(validation.reason, validation.record) : undefined) ??
    (validation.status === 'valid' && validation.proxy ? proxiedLabel : undefined) ??
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
        <Typography variant="caption">Freepod address</Typography>
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
            onChange={(e) => {
              autoNameRef.current = null
              setPrefix(e.target.value.replace(/\./g, ''))
            }}
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
                      {suffix}
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
              CNAME → {cnameDomain}, or A/AAAA records matching it for a root domain ·{' '}
              <Link href={proxied ? CLOUDFLARE_GUIDE : SETUP_GUIDE} target="_blank" rel="noopener">
                Setup guide
              </Link>
            </Typography>
          </>
        )}
      </Box>

      {helperText && <FormHelperText>{helperText}</FormHelperText>}
    </FormControl>
  )
}
