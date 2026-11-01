import { useState } from 'react'
import { Box, Button, Stack, TextField } from '@mui/material'

interface AccessAddFormProps {
  /** Adds the address; rejects with the reason to show beside the field. */
  onAdd: (email: string) => Promise<void>
  describeError: (err: unknown, email: string) => string
}

/** "Add someone by email". A refused address stays in the field with the reason below it. */
export function AccessAddForm({ onAdd, describeError }: AccessAddFormProps) {
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim()) return
    setBusy(true)
    setError(null)
    try {
      await onAdd(email.trim())
      setEmail('')
    } catch (err) {
      setError(describeError(err, email))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Box component="form" onSubmit={submit} noValidate>
      <Stack direction="row" spacing={1.25} alignItems="flex-start">
        <TextField
          label="Add someone by email"
          placeholder="name@example.com"
          type="email"
          autoComplete="off"
          size="small"
          fullWidth
          value={email}
          onChange={(e) => { setEmail(e.target.value); setError(null) }}
          error={Boolean(error)}
          helperText={error ?? ' '}
          slotProps={{ inputLabel: { shrink: true } }}
        />
        <Button type="submit" variant="contained" disabled={busy || !email.trim()} sx={{ flex: '0 0 auto', mt: '1px', minWidth: 72 }}>
          {busy ? 'Adding…' : 'Add'}
        </Button>
      </Stack>
    </Box>
  )
}
