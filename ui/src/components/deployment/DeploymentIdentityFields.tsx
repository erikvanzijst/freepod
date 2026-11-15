import { useRef, useState } from 'react'
import { Box, Button, Stack, TextField, Typography } from '@mui/material'
import { resolveApiPath } from '../../api/client'
import type { Deployment } from '../../api/types'
import AppIcon from '../apppage/AppIcon'
import { ManagedFieldNotice } from './ManagedFieldNotice'
import { ICON_TYPES, readIcon, type IdentityDraft } from './identityDraft'

interface DeploymentIdentityFieldsProps {
  deployment: Deployment
  value: IdentityDraft
  onChange: (draft: IdentityDraft) => void
  nameError?: string
  onTakeOver?: (key: string) => void
  takingOver?: boolean
  disabled?: boolean
}

/** The deployment's own name, description and icon, above its app settings. */
export function DeploymentIdentityFields({
  deployment,
  value,
  onChange,
  nameError,
  onTakeOver,
  takingOver,
  disabled,
}: DeploymentIdentityFieldsProps) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [iconError, setIconError] = useState<string | null>(null)
  const managed = new Set(deployment.managed_fields ?? [])
  const product = deployment.desired_template?.product
  const productIcon = product?.icon_url ? resolveApiPath(product.icon_url) : null
  const ownIcon =
    value.icon === null ? null : value.iconPreview ?? (deployment.icon_url ? resolveApiPath(deployment.icon_url) : null)
  const isDefaultIcon = ownIcon === null
  const notice = (key: string, label: string) =>
    managed.has(key) ? (
      <ManagedFieldNotice label={label} takingOver={takingOver} onTakeOver={onTakeOver && (() => onTakeOver(key))} />
    ) : null

  const pick = async (file: File | undefined) => {
    if (!file) return
    try {
      const { base64, preview } = await readIcon(file)
      setIconError(null)
      onChange({ ...value, icon: base64, iconPreview: preview })
    } catch (e) {
      setIconError((e as Error).message)
    }
  }

  return (
    <Stack spacing={2} data-testid="deployment-identity">
      <Stack spacing={1}>
        {notice('name', 'Name')}
        <TextField
          label="Name"
          required
          value={value.name}
          onChange={(e) => onChange({ ...value, name: e.target.value })}
          error={Boolean(nameError)}
          helperText={nameError}
          slotProps={{ input: { readOnly: disabled || managed.has('name') }, htmlInput: { maxLength: 100 } }}
        />
      </Stack>
      <Stack spacing={1}>
        {notice('description', 'Description')}
        <TextField
          label="Description"
          multiline
          minRows={2}
          value={value.description}
          placeholder={product?.tagline ?? undefined}
          onChange={(e) => onChange({ ...value, description: e.target.value })}
          slotProps={{ input: { readOnly: disabled || managed.has('description') }, htmlInput: { maxLength: 500 } }}
        />
      </Stack>
      <Stack spacing={1}>
        {notice('icon', 'Icon')}
        <Stack direction="row" spacing={2} alignItems="center">
          <AppIcon name={value.name || product?.name || 'App'} src={ownIcon ?? productIcon} size={48} />
          <Box sx={{ flex: 1 }}>
            <Typography variant="body2">Icon</Typography>
            <Typography variant="body2" color={iconError ? 'error' : 'text.secondary'}>
              {iconError ?? (isDefaultIcon ? `${product?.name ?? 'The app'}'s icon (default)` : 'Your own icon')}
            </Typography>
          </Box>
          {!managed.has('icon') && !disabled && (
            <>
              <input
                ref={fileRef}
                type="file"
                accept={ICON_TYPES.join(',')}
                hidden
                data-testid="icon-file"
                onChange={(e) => {
                  void pick(e.target.files?.[0])
                  e.target.value = ''
                }}
              />
              <Button size="small" variant="outlined" onClick={() => fileRef.current?.click()}>
                Upload
              </Button>
              {!isDefaultIcon && (
                <Button size="small" onClick={() => onChange({ ...value, icon: null, iconPreview: undefined })}>
                  Reset
                </Button>
              )}
            </>
          )}
        </Stack>
      </Stack>
    </Stack>
  )
}
