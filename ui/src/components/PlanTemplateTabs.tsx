import { useEffect, useMemo, useState } from 'react'
import {
  Box,
  Button,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import StarIcon from '@mui/icons-material/Star'
import AddIcon from '@mui/icons-material/Add'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createPlanTemplate, updatePlan } from '../api/endpoints'
import type { Plan, PlanTemplatePayload, PlanTemplateVersion } from '../api/types'
import { formatDateTime } from '../utils/format'
import { SplitPane } from './SplitPane'
import { PlanCardPreview } from './PlanCardPreview'

function formatPrice(cents: number): string {
  return cents === 0 ? 'Free' : `€${(cents / 100).toFixed(cents % 100 === 0 ? 0 : 2)}`
}

function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return 'None'
  if (bytes >= 1024 ** 4) return `${(bytes / 1024 ** 4).toFixed(1)} TB`
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(0)} MB`
  return `${bytes} B`
}

interface PlanTemplateTabsProps {
  plan: Plan
  templates: PlanTemplateVersion[]
  onError: (error: Error) => void
}

export function PlanTemplateTabs({ plan, templates, onError }: PlanTemplateTabsProps) {
  const queryClient = useQueryClient()

  const sorted = useMemo(
    () => [...templates].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()),
    [templates],
  )

  const defaultTab = (tpls: typeof sorted): number | 'new' => {
    if (tpls.length === 0) return 'new'
    if (plan.template_id && tpls.some((t) => t.id === plan.template_id)) {
      return plan.template_id
    }
    return tpls[tpls.length - 1].id
  }

  const [activeTab, setActiveTab] = useState<number | 'new'>(() => defaultTab(sorted))

  useEffect(() => {
    setActiveTab(defaultTab(sorted))
  }, [sorted, plan.template_id]) // eslint-disable-line react-hooks/exhaustive-deps

  const makeCanonicalMutation = useMutation({
    mutationFn: (templateId: number) => updatePlan(plan.id, { template_id: templateId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plans'] })
    },
    onError,
  })

  const createMutation = useMutation({
    mutationFn: (payload: PlanTemplatePayload) => createPlanTemplate(plan.id, payload),
    onSuccess: (tmpl) => {
      queryClient.invalidateQueries({ queryKey: ['plan-templates', plan.id] })
      if (!plan.template_id) {
        makeCanonicalMutation.mutate(tmpl.id)
      }
      setActiveTab(tmpl.id)
    },
    onError,
  })

  const activeTemplate = sorted.find((t) => t.id === activeTab)

  return (
    <>
      <Tabs
        value={activeTab}
        onChange={(_, value) => setActiveTab(value)}
        variant="scrollable"
        scrollButtons="auto"
        sx={{ borderBottom: 1, borderColor: 'divider' }}
      >
        {sorted.map((tmpl) => (
          <Tab
            key={tmpl.id}
            value={tmpl.id}
            icon={plan.template_id === tmpl.id ? <StarIcon sx={{ fontSize: 16 }} /> : undefined}
            iconPosition="start"
            label={`#${tmpl.id}`}
            sx={{ minHeight: 48 }}
          />
        ))}
        <Tab
          value="new"
          icon={<AddIcon sx={{ fontSize: 16 }} />}
          iconPosition="start"
          label="New"
          sx={{ minHeight: 48, ml: 'auto' }}
        />
      </Tabs>
      <Box sx={{ p: 2 }}>
        {activeTab === 'new' ? (
          <NewPlanTemplateForm
            plan={plan}
            lastTemplate={sorted.length > 0 ? sorted[sorted.length - 1] : undefined}
            onSave={(payload) => createMutation.mutate(payload)}
            saving={createMutation.isPending}
          />
        ) : activeTemplate ? (
          <PlanTemplateReadOnly
            plan={plan}
            template={activeTemplate}
            isCanonical={plan.template_id === activeTemplate.id}
            onMakeCanonical={() => makeCanonicalMutation.mutate(activeTemplate.id)}
          />
        ) : null}
      </Box>
    </>
  )
}

// ---------------------------------------------------------------------------
// Read-only view for an existing plan template version
// ---------------------------------------------------------------------------

interface PlanTemplateReadOnlyProps {
  plan: Plan
  template: PlanTemplateVersion
  isCanonical: boolean
  onMakeCanonical: () => void
}

function PlanTemplateReadOnly({ plan, template, isCanonical, onMakeCanonical }: PlanTemplateReadOnlyProps) {
  return (
    <SplitPane
      left={
        <Stack spacing={2}>
          <Stack direction="row" spacing={4} flexWrap="wrap">
            <Box>
              <Typography variant="caption" color="text.secondary">Price</Typography>
              <Typography variant="h6">{formatPrice(template.price_cents)}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Billing interval</Typography>
              <Typography variant="h6" sx={{ textTransform: 'capitalize' }}>{template.billing_interval}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Storage</Typography>
              <Typography variant="h6">{formatBytes(template.storage_bytes)}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Database</Typography>
              <Typography variant="h6">{formatBytes(template.database_bytes)}</Typography>
            </Box>
          </Stack>
          {template.description && (
            <Box>
              <Typography variant="caption" color="text.secondary">Description (Markdown)</Typography>
              <TextField
                value={template.description}
                multiline
                fullWidth
                size="small"
                slotProps={{ input: { readOnly: true } }}
                sx={{ mt: 0.5 }}
              />
            </Box>
          )}
          <Typography variant="caption" color="text.secondary">
            Created {formatDateTime(template.created_at)}
          </Typography>
          {isCanonical ? (
            <Button variant="outlined" disabled startIcon={<StarIcon />} sx={{ alignSelf: 'flex-start' }}>
              Canonical
            </Button>
          ) : (
            <Button variant="outlined" onClick={onMakeCanonical} startIcon={<StarIcon />} sx={{ alignSelf: 'flex-start' }}>
              Make canonical
            </Button>
          )}
        </Stack>
      }
      right={
        <Box>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Card preview
          </Typography>
          <PlanCardPreview
            name={plan.name}
            priceCents={template.price_cents}
            billingInterval={template.billing_interval}
            description={template.description}
          />
        </Box>
      }
    />
  )
}

// ---------------------------------------------------------------------------
// Form for creating a new plan template version
// ---------------------------------------------------------------------------

interface NewPlanTemplateFormProps {
  plan: Plan
  lastTemplate?: PlanTemplateVersion
  onSave: (payload: PlanTemplatePayload) => void
  saving: boolean
}

function NewPlanTemplateForm({ plan, lastTemplate, onSave, saving }: NewPlanTemplateFormProps) {
  const [priceEuros, setPriceEuros] = useState(lastTemplate ? String(lastTemplate.price_cents / 100) : '')
  const [billingInterval, setBillingInterval] = useState<string>(lastTemplate?.billing_interval ?? 'monthly')
  const [storageGb, setStorageGb] = useState(
    lastTemplate?.storage_bytes ? String(lastTemplate.storage_bytes / 1024 ** 3) : '',
  )
  // Database allowances are entered in MB: the smallest tier is 100 MB, which
  // as a fraction of a GB is unreadable.
  const [databaseMb, setDatabaseMb] = useState(
    lastTemplate?.database_bytes ? String(lastTemplate.database_bytes / 1024 ** 2) : '',
  )
  const [description, setDescription] = useState(lastTemplate?.description ?? '')

  function handleSubmit() {
    const cents = Math.round(parseFloat(priceEuros) * 100)
    if (isNaN(cents) || cents < 0) return
    const storageBytes = storageGb ? Math.round(parseFloat(storageGb) * 1024 ** 3) : null
    const databaseBytes = databaseMb ? Math.round(parseFloat(databaseMb) * 1024 ** 2) : null
    onSave({
      price_cents: cents,
      billing_interval: billingInterval,
      storage_bytes: storageBytes,
      database_bytes: databaseBytes,
      description: description.trim() || null,
    })
    setPriceEuros('')
    setStorageGb('')
    setDatabaseMb('')
    setDescription('')
  }

  const valid = priceEuros !== '' && !isNaN(parseFloat(priceEuros)) && parseFloat(priceEuros) >= 0

  // Live preview values
  const previewCents = valid ? Math.round(parseFloat(priceEuros) * 100) : null

  return (
    <SplitPane
      left={
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField
            label="Price (€)"
            value={priceEuros}
            onChange={(e) => setPriceEuros(e.target.value)}
            type="number"
            size="small"
            autoFocus
            helperText="Enter 0 for a free plan"
            slotProps={{ htmlInput: { min: 0, step: 0.01 } }}
          />
          <TextField
            label="Billing interval"
            value={billingInterval}
            onChange={(e) => setBillingInterval(e.target.value)}
            size="small"
            select
          >
            <MenuItem value="monthly">Monthly</MenuItem>
            <MenuItem value="annual">Annual</MenuItem>
          </TextField>
          <TextField
            label="Storage (GB)"
            value={storageGb}
            onChange={(e) => setStorageGb(e.target.value)}
            type="number"
            size="small"
            helperText="Leave empty for no storage limit"
            slotProps={{ htmlInput: { min: 0 } }}
          />
          <TextField
            label="Database (MB)"
            value={databaseMb}
            onChange={(e) => setDatabaseMb(e.target.value)}
            type="number"
            size="small"
            helperText="Leave empty for no database"
            slotProps={{ htmlInput: { min: 0 } }}
          />
          <TextField
            label="Description (Markdown)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            size="small"
            multiline
            minRows={4}
            fullWidth
          />
          <Button
            variant="contained"
            onClick={handleSubmit}
            disabled={!valid || saving}
            sx={{ alignSelf: 'flex-start' }}
          >
            {saving ? 'Creating...' : 'Create template'}
          </Button>
        </Stack>
      }
      right={
        <Box>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Card preview
          </Typography>
          <PlanCardPreview
            name={plan.name}
            priceCents={previewCents}
            billingInterval={billingInterval}
            description={description || null}
          />
        </Box>
      }
    />
  )
}
