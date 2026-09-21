import { Dialog, DialogContent } from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { createDeployment, updateDeployment, listTemplates, listPlans, getDeployment, getTosAcceptance, recordTosAcceptance } from '../api/endpoints'
import type { Deployment, Plan, Product, ProductTemplate } from '../api/types'
import { validateUserValues } from './UserValuesForm'
import type { VarSubmission } from './UserValuesForm'
import { DeployDialogContent } from './DeployDialogContent'
import { LEGAL_DOCS } from '../content/legal'

// Version (effective date) of the Terms of Service this build displays; recorded
// as the user's acceptance on first launch. Sourced from the bundled document so
// it stays in lockstep with the text shown in the agreement modal.
const TOS_VERSION = LEGAL_DOCS.terms.version

interface DeployDialogProps {
  product: Product
  userId: number
  onClose: () => void
  deployment?: Deployment
}

export function DeployDialog({ product, userId, onClose, deployment }: DeployDialogProps) {
  const queryClient = useQueryClient()
  const [userValues, setUserValues] = useState<Record<string, unknown> | null>(null)
  const [vars, setVars] = useState<Record<string, VarSubmission>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [userValuesErrors, setUserValuesErrors] = useState<string[]>([])
  const [hostnameValid, setHostnameValid] = useState(true)
  const [requiredFilled, setRequiredFilled] = useState(true)
  const [selectedPlanTemplateId, setSelectedPlanTemplateId] = useState<number | null>(null)
  const [tosAccepted, setTosAccepted] = useState(false)

  const isEditMode = Boolean(deployment)

  const templatesQuery = useQuery({
    queryKey: ['templates', product.id],
    queryFn: () => listTemplates(product.id),
    enabled: !isEditMode,
  })

  const plansQuery = useQuery({
    queryKey: ['plans', product.id],
    queryFn: () => listPlans(product.id),
    enabled: !isEditMode,
  })

  // Whether the current user has already accepted the current Terms. Only new
  // launches care; a null version means "not yet accepted" -> show the checkbox.
  const tosAcceptanceQuery = useQuery({
    queryKey: ['tos-acceptance'],
    queryFn: getTosAcceptance,
    enabled: !isEditMode,
  })
  const hasAcceptedTos = tosAcceptanceQuery.data?.version != null

  // The deployment's own read, which the listing cannot answer: vars and
  // `pending` are reported per deployment, not inlined into a list. Needed
  // here to prefill the form -- a sensitive var arrives with no value, which
  // is what tells the field to render as "currently set".
  const deploymentQuery = useQuery({
    queryKey: ['deployment', userId, deployment?.id],
    queryFn: () => getDeployment(userId, deployment!.id),
    enabled: isEditMode && Boolean(deployment?.id),
  })
  const currentVars = deploymentQuery.data?.vars ?? null
  const varsPending = deploymentQuery.data?.pending === true

  const canonicalTemplate: ProductTemplate | undefined = useMemo(() => {
    return templatesQuery.data?.find((t) => t.id === product.template_id)
  }, [templatesQuery.data, product.template_id])

  const activeTemplate: ProductTemplate | undefined = isEditMode
    ? deployment!.desired_template
    : canonicalTemplate

  const plans: Plan[] = useMemo(() => {
    if (isEditMode) {
      // Show the deployment's current plan as a read-only display
      const plan = deployment?.subscription?.plan_template?.plan
      return plan ? [{ ...plan, template: deployment?.subscription?.plan_template ?? null }] : []
    }
    return (plansQuery.data ?? []).filter((p) => p.template_id != null)
  }, [isEditMode, deployment, plansQuery.data])

  // Auto-select if there's only one plan
  const effectivePlanTemplateId = useMemo(() => {
    if (isEditMode) return null
    if (selectedPlanTemplateId) return selectedPlanTemplateId
    if (plans.length === 1 && plans[0].template_id) return plans[0].template_id
    return null
  }, [isEditMode, selectedPlanTemplateId, plans])

  const createMutation = useMutation({
    mutationFn: async (payload: {
      templateId: number
      userValuesJson?: object
      planTemplateId?: number
      vars?: Record<string, VarSubmission>
    }) => {
      // First launch: record ToS acceptance (a separate user-level resource)
      // before creating the deployment. Already-accepted users skip this. If
      // acceptance fails (e.g. the terms changed -> 409), the error surfaces and
      // no deployment is created.
      if (!hasAcceptedTos) {
        await recordTosAcceptance(TOS_VERSION)
        queryClient.invalidateQueries({ queryKey: ['tos-acceptance'] })
      }
      return createDeployment(userId, {
        desired_template_id: payload.templateId,
        user_values_json: payload.userValuesJson,
        plan_template_id: payload.planTemplateId,
        vars: payload.vars,
      })
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['deployments'] })
      if (data.checkout_url) {
        window.location.href = data.checkout_url
      } else {
        onClose()
      }
    },
    onError: (error: Error) => {
      const errorMsg = error.message
      if (errorMsg.startsWith('vars.')) {
        // A rejected var names the key it rejected, so the form can match it to
        // a field and say what is wrong beneath it. Re-running the chart-side
        // validation here would find nothing: a var is not a chart value.
        setUserValuesErrors([errorMsg])
      } else if (errorMsg.includes('user_values_json') || errorMsg.includes('validation')) {
        const validationErrors = validateUserValues(
          activeTemplate?.values_schema_json ?? null,
          userValues,
        )
        setUserValuesErrors(validationErrors.length > 0 ? validationErrors : [errorMsg])
      } else {
        setFormError(error.message)
      }
    },
  })

  const updateMutation = useMutation({
    mutationFn: (payload: {
      templateId: number
      userValuesJson?: object
      vars?: Record<string, VarSubmission>
    }) =>
      updateDeployment(userId, deployment!.id, {
        desired_template_id: payload.templateId,
        user_values_json: payload.userValuesJson,
        vars: payload.vars,
        // Passed through explicitly. The platform does not yet infer it, so an
        // update that omits it drops the new release's link to the build that
        // produced the image it is running.
        build_id: deploymentQuery.data?.applied_release?.build_id ?? undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deployments'] })
      queryClient.invalidateQueries({ queryKey: ['deployment', userId, deployment?.id] })
      onClose()
    },
    onError: (error: Error) => {
      const errorMsg = error.message
      if (errorMsg.includes('not in ready state')) {
        setFormError('This deployment cannot be updated right now. It may be provisioning or was modified by another process.')
      } else if (errorMsg.startsWith('vars.')) {
        // See the create mutation: a var error belongs beside its field.
        setUserValuesErrors([errorMsg])
      } else if (errorMsg.includes('user_values_json') || errorMsg.includes('validation')) {
        const validationErrors = validateUserValues(
          activeTemplate?.values_schema_json ?? null,
          userValues,
        )
        setUserValuesErrors(validationErrors.length > 0 ? validationErrors : [errorMsg])
      } else {
        setFormError(error.message)
      }
    },
  })

  const activeMutation = isEditMode ? updateMutation : createMutation

  const handleLaunch = useCallback(() => {
    const templateId = isEditMode ? deployment!.desired_template_id : product.template_id
    if (!templateId) return

    if (activeTemplate?.values_schema_json) {
      const validationErrors = validateUserValues(
        activeTemplate.values_schema_json as Record<string, unknown>,
        userValues,
      )
      if (validationErrors.length > 0) {
        setUserValuesErrors(validationErrors)
        return
      }
    }

    setUserValuesErrors([])
    const valuesToSend = userValues ?? {}
    // Omitted rather than sent empty, so a product whose schema marks nothing
    // runtime submits exactly the payload it always did.
    const varsToSend = Object.keys(vars).length > 0 ? vars : undefined
    if (isEditMode) {
      updateMutation.mutate({
        templateId,
        userValuesJson: valuesToSend,
        vars: varsToSend,
      })
    } else {
      createMutation.mutate({
        templateId,
        userValuesJson: valuesToSend,
        planTemplateId: effectivePlanTemplateId ?? undefined,
        vars: varsToSend,
      })
    }
  }, [product.template_id, deployment, isEditMode, activeTemplate, userValues, vars, effectivePlanTemplateId, createMutation, updateMutation])

  // Applying staged vars is an ordinary redeploy: the release the platform
  // mints captures whatever the deployment's vars currently are. Nothing about
  // the form is submitted, so a half-edited field cannot ride along.
  const handleApplyPendingVars = useCallback(() => {
    const templateId = deployment?.desired_template_id
    if (!templateId) return
    updateMutation.mutate({ templateId })
  }, [deployment, updateMutation])

  const initialValuesJson = isEditMode
    ? (deployment!.user_values_json as Record<string, unknown> | null) ?? null
    : null

  // Widen dialog when there are multiple plans
  const dialogMaxWidth = !isEditMode && plans.length > 2 ? 'md' as const : 'sm' as const

  return (
    <Dialog open onClose={onClose} maxWidth={dialogMaxWidth} fullWidth>
      <DialogContent sx={{ pt: 3 }}>
        <DeployDialogContent
          product={product}
          valuesSchemaJson={
            (activeTemplate?.values_schema_json as Record<string, unknown> | null) ?? null
          }
          initialValuesJson={initialValuesJson}
          onChange={setUserValues}
          onVarsChange={setVars}
          initialVars={currentVars}
          varsPending={varsPending}
          onApplyPendingVars={isEditMode ? handleApplyPendingVars : undefined}
          applyingPendingVars={updateMutation.isPending}
          onHostnameValidationChange={setHostnameValid}
          onRequiredFilledChange={setRequiredFilled}
          onLaunch={handleLaunch}
          onCancel={onClose}
          launchDisabled={
            activeMutation.isPending ||
            !activeTemplate ||
            !hostnameValid ||
            !requiredFilled ||
            (!isEditMode && !effectivePlanTemplateId) ||
            (!isEditMode && !hasAcceptedTos && !tosAccepted)
          }
          launchHint={requiredFilled ? undefined : 'Fill in every field marked * to continue.'}
          launchPending={activeMutation.isPending}
          formError={formError}
          userValuesErrors={userValuesErrors}
          noTemplateWarning={!isEditMode && !templatesQuery.isLoading && !canonicalTemplate}
          loading={!isEditMode && (templatesQuery.isLoading || plansQuery.isLoading)}
          initialHostname={deployment?.hostname ?? undefined}
          submitLabel={isEditMode ? 'Update' : 'Launch'}
          plans={plans}
          selectedPlanTemplateId={isEditMode ? (deployment?.subscription?.plan_template?.id ?? null) : effectivePlanTemplateId}
          onSelectPlan={isEditMode ? undefined : (planTemplateId) => setSelectedPlanTemplateId(planTemplateId)}
          showTosAgreement={!isEditMode && !hasAcceptedTos}
          tosAccepted={tosAccepted}
          onTosAcceptedChange={setTosAccepted}
        />
      </DialogContent>
    </Dialog>
  )
}
