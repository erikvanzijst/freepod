import {
  Alert,
  Avatar,
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Grid,
  Stack,
  Typography,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import { resolveApiPath } from '../api/client'
import type { Plan, Product } from '../api/types'
import { UserValuesForm } from './UserValuesForm'
import type { VarSubmission } from './UserValuesForm'
import { PendingVarsNotice } from './PendingVarsNotice'
import { PlanCardContent } from './PlanCardContent'
import { TosAgreement } from './TosAgreement'

interface DeployDialogContentProps {
  product: Product
  valuesSchemaJson: Record<string, unknown> | null
  initialValuesJson: Record<string, unknown> | null
  onChange: (userValues: Record<string, unknown> | null) => void
  onVarsChange?: (vars: Record<string, VarSubmission>) => void
  initialVars?: Record<string, { value?: string; sensitive: boolean }> | null
  /** Whether a rollout would change the running pod's environment. */
  varsPending?: boolean
  onApplyPendingVars?: () => void
  applyingPendingVars?: boolean
  onHostnameValidationChange?: (valid: boolean) => void
  onRequiredFilledChange?: (filled: boolean) => void
  onLaunch?: () => void
  onCancel?: () => void
  launchDisabled?: boolean
  /** Why Launch is disabled, when the reason is something the user can fix. */
  launchHint?: string
  launchPending?: boolean
  formError?: string | null
  userValuesErrors?: string[]
  noTemplateWarning?: boolean
  loading?: boolean
  initialHostname?: string
  submitLabel?: string
  readOnly?: boolean
  plans?: Plan[]
  selectedPlanTemplateId?: number | null
  onSelectPlan?: (planTemplateId: number) => void
  showTosAgreement?: boolean
  tosAccepted?: boolean
  onTosAcceptedChange?: (accepted: boolean) => void
}

export function DeployDialogContent({
  product,
  valuesSchemaJson,
  initialValuesJson,
  onChange,
  onVarsChange,
  initialVars,
  varsPending,
  onApplyPendingVars,
  applyingPendingVars,
  onHostnameValidationChange,
  onRequiredFilledChange,
  onLaunch,
  onCancel,
  launchDisabled,
  launchHint,
  launchPending,
  formError,
  userValuesErrors = [],
  noTemplateWarning,
  loading,
  initialHostname,
  submitLabel = 'Launch',
  readOnly,
  plans,
  selectedPlanTemplateId,
  onSelectPlan,
  showTosAgreement,
  tosAccepted = false,
  onTosAcceptedChange,
}: DeployDialogContentProps) {
  return (
    <>
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
        <Avatar
          src={product.icon_url ? resolveApiPath(product.icon_url) : undefined}
          alt={product.name}
          variant="rounded"
          sx={{ width: 48, height: 48 }}
        >
          {product.name[0]}
        </Avatar>
        <Box>
          <Typography variant="h6">{product.name}</Typography>
          {product.description && (
            <Typography variant="body2" color="text.secondary">
              {product.description}
            </Typography>
          )}
        </Box>
      </Stack>

      {plans && plans.length > 0 && (
        <Box sx={{ mb: 3 }}>
          {onSelectPlan && (
            <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
              Select a plan:
            </Typography>
          )}
          <Grid container spacing={1.5}>
            {plans.map((plan) => {
              const tmpl = plan.template
              const isSelected = tmpl && selectedPlanTemplateId === tmpl.id
              const cardContent = (
                <CardContent sx={{ py: 1.5, px: 2 }}>
                  <PlanCardContent
                    name={plan.name}
                    priceCents={tmpl?.price_cents}
                    billingInterval={tmpl?.billing_interval}
                    description={tmpl?.description}
                    compact
                    nameVariant="subtitle2"
                    priceVariant="h6"
                    nameAdornment={
                      isSelected
                        ? <CheckCircleIcon sx={{ fontSize: 18, color: 'primary.main' }} />
                        : undefined
                    }
                  />
                </CardContent>
              )
              return (
                <Grid key={plan.id} size={{ xs: 12, sm: plans.length <= 2 ? 6 : 4 }}>
                  <Card
                    variant="outlined"
                    sx={{
                      height: '100%',
                      borderColor: isSelected ? 'primary.main' : 'divider',
                      borderWidth: isSelected ? 2 : 1,
                      bgcolor: isSelected ? 'action.selected' : undefined,
                    }}
                  >
                    {onSelectPlan ? (
                      <CardActionArea
                        onClick={() => tmpl && onSelectPlan(tmpl.id)}
                        sx={{
                          height: '100%',
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'stretch',
                          justifyContent: 'flex-start',
                        }}
                      >
                        {cardContent}
                      </CardActionArea>
                    ) : (
                      cardContent
                    )}
                  </Card>
                </Grid>
              )
            })}
          </Grid>
        </Box>
      )}

      <Stack spacing={2}>
        {formError && <Alert severity="error">{formError}</Alert>}
        {varsPending && onApplyPendingVars && (
          <PendingVarsNotice
            pending
            onApply={onApplyPendingVars}
            applying={applyingPendingVars}
            disabled={readOnly}
          />
        )}
        {loading ? (
          <Typography color="text.secondary">Loading...</Typography>
        ) : noTemplateWarning ? (
          <Alert severity="warning">
            This product has no template configured yet.
          </Alert>
        ) : (
          <UserValuesForm
            valuesSchemaJson={valuesSchemaJson}
            initialValuesJson={initialValuesJson}
            initialVars={initialVars}
            onChange={onChange}
            onVarsChange={onVarsChange}
            onHostnameValidationChange={onHostnameValidationChange}
            onRequiredFilledChange={onRequiredFilledChange}
            errors={userValuesErrors}
            initialHostname={initialHostname}
            readOnly={readOnly}
          />
        )}
      </Stack>
      {showTosAgreement && !loading && (
        <Box sx={{ mt: 2.5 }}>
          <TosAgreement checked={tosAccepted} onChange={(v) => onTosAcceptedChange?.(v)} />
        </Box>
      )}
      {(onCancel || onLaunch) && (
        <Stack direction="row" spacing={1} justifyContent="flex-end" alignItems="center" sx={{ mt: 3 }}>
          {launchHint && (
            <Typography variant="body2" color="text.secondary" sx={{ mr: 'auto' }}>
              {launchHint}
            </Typography>
          )}
          {onCancel && <Button onClick={onCancel} variant="outlined">Cancel</Button>}
          {onLaunch && (
            <Button
              variant="contained"
              onClick={onLaunch}
              disabled={launchDisabled}
            >
              {launchPending ? `${submitLabel === 'Launch' ? 'Launching' : 'Updating'}...` : submitLabel}
            </Button>
          )}
        </Stack>
      )}
    </>
  )
}
