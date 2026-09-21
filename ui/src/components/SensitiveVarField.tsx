import { useState } from 'react'
import { FormControl, FormHelperText, IconButton, InputAdornment, TextField, Tooltip } from '@mui/material'
import VisibilityIcon from '@mui/icons-material/Visibility'
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff'

interface SensitiveVarFieldProps {
  label: string
  description?: string
  required?: boolean
  error?: string
  readOnly?: boolean
  /** Whether the deployment already holds a value for this var. */
  alreadySet: boolean
  /** Whether the user has typed into this field during this session. */
  touched: boolean
  value: string
  onChange: (value: string) => void
}

/**
 * A write-only var: a password input that never displays a stored value.
 *
 * The platform cannot prefill it and deliberately does not try — a read of a
 * sensitive var omits its value entirely, so there is nothing to show. What
 * the field has to communicate instead is that leaving it alone is safe: an
 * untouched field submits no value at all, and the stored one is kept.
 *
 * The alternative, prefilling with a placeholder like `••••••`, invites the
 * user to submit the mask back as the new value, and an empty string would
 * wipe the secret outright.
 *
 * The reveal toggle only ever shows what the user typed here, which is why it
 * appears only once the field holds something: on an empty field there is
 * nothing to reveal, and offering the control would suggest the stored secret
 * can be read back. Typing a secret the user can verify is what removes the
 * need for a confirmation field.
 */
export function SensitiveVarField({
  label,
  description,
  required,
  error,
  readOnly,
  alreadySet,
  touched,
  value,
  onChange,
}: SensitiveVarFieldProps) {
  const [revealed, setRevealed] = useState(false)
  const unchanged = alreadySet && !touched
  const helper =
    error ??
    (unchanged
      ? description
        ? `${description} — currently set; leave blank to keep it.`
        : 'Currently set. Leave blank to keep it, or type a new value to replace it.'
      : description)

  return (
    <FormControl fullWidth error={!!error}>
      <TextField
        type={revealed ? 'text' : 'password'}
        label={label}
        value={value}
        placeholder={unchanged ? 'unchanged' : undefined}
        onChange={(e) => {
          // Never leave a cleared field revealed: the next thing typed into
          // it would be on screen before the user asked for that.
          if (!e.target.value) setRevealed(false)
          onChange(e.target.value)
        }}
        // Not `required` while a stored value exists: the field being empty
        // means "keep what is there", which satisfies the requirement.
        required={required && !alreadySet}
        error={!!error}
        autoComplete="new-password"
        helperText={helper}
        slotProps={{
          input: {
            ...(readOnly ? { readOnly: true } : {}),
            endAdornment: value ? (
              <InputAdornment position="end">
                <Tooltip title={revealed ? 'Hide password' : 'Show password'}>
                  <IconButton
                    size="small"
                    edge="end"
                    aria-label={revealed ? 'Hide password' : 'Show password'}
                    onClick={() => setRevealed((v) => !v)}
                    // The field itself keeps focus, so tabbing runs through
                    // the form rather than stopping on a display control.
                    tabIndex={-1}
                  >
                    {revealed ? (
                      <VisibilityOffIcon fontSize="small" />
                    ) : (
                      <VisibilityIcon fontSize="small" />
                    )}
                  </IconButton>
                </Tooltip>
              </InputAdornment>
            ) : undefined,
          },
        }}
      />
      {/* No error helper here: `helper` above already resolves to the error
          when there is one, and a second one renders the same message twice. */}
    </FormControl>
  )
}
