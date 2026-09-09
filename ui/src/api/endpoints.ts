import { requestJson, requestMultipart } from './client'
import type { Deployment, DeploymentCreateResponse, DeploymentDatabase, HostnameCheckResult, Plan, PlanTemplatePayload, PlanTemplateVersion, Product, ProductTemplate, ProductVisibility, SftpCredentials, SshKey, Subdomain, TosAcceptance, User, VarWrite } from './types'

export function getMe() {
  return requestJson<User>('/me')
}

export function getTosAcceptance() {
  return requestJson<TosAcceptance>('/me/tos-acceptance')
}

export function recordTosAcceptance(version: string) {
  return requestJson<TosAcceptance>('/me/tos-acceptance', {
    method: 'POST',
    body: JSON.stringify({ version }),
  })
}

export function getMySubdomain() {
  return requestJson<Subdomain>('/me/subdomain')
}

/**
 * Claim the account's permanent address. Refused with `subdomain_already_claimed`
 * once one is held — there is no second claim, and no way back.
 */
export function claimSubdomain(subdomain: string) {
  return requestJson<Subdomain>('/me/subdomain', {
    method: 'POST',
    body: JSON.stringify({ subdomain }),
  })
}

export function listUsers() {
  return requestJson<User[]>('/users')
}

/**
 * List the products the caller may see: public products for anonymous
 * visitors and regular users, every non-deleted product for admins.
 */
export function listProducts() {
  return requestJson<Product[]>('/products')
}

export function createProduct(
  payload: {
    name: string
    description?: string | null
    category?: string | null
    replaces?: string | null
    visibility?: ProductVisibility
  },
  iconFile?: File,
) {
  if (iconFile) {
    return requestMultipart<Product>('/products', payload, { field: 'icon', file: iconFile })
  }
  return requestJson<Product>('/products', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function deleteProduct(productId: number) {
  return requestJson<null>(`/products/${productId}`, { method: 'DELETE' })
}

export function updateProduct(
  productId: number,
  payload: {
    name?: string
    description?: string | null
    template_id?: number
    category?: string | null
    replaces?: string | null
    visibility?: ProductVisibility
  },
  iconFile?: File,
) {
  if (iconFile) {
    return requestMultipart<Product>(
      `/products/${productId}`,
      payload,
      { field: 'icon', file: iconFile },
      {},
      'PUT',
    )
  }
  return requestJson<Product>(`/products/${productId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function updateProductTemplate(productId: number, templateId: number) {
  return updateProduct(productId, { template_id: templateId })
}

export function listTemplates(productId: number) {
  return requestJson<ProductTemplate[]>(`/products/${productId}/templates`)
}

export function createTemplate(
  productId: number,
  payload: { chart_ref: string; chart_version: string; values_schema_json?: object; system_values_json?: object },
) {
  return requestJson<ProductTemplate>(`/products/${productId}/templates`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function deleteTemplate(productId: number, templateId: number) {
  return requestJson<null>(`/products/${productId}/templates/${templateId}`, {
    method: 'DELETE',
  })
}

export function listPlans(productId: number) {
  return requestJson<Plan[]>(`/products/${productId}/plans`)
}

export function createPlan(productId: number, payload: { name: string; sort_order?: number | null }) {
  return requestJson<Plan>(`/products/${productId}/plans`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updatePlan(planId: number, payload: { name?: string; template_id?: number; sort_order?: number | null }) {
  return requestJson<Plan>(`/plans/${planId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function deletePlan(planId: number) {
  return requestJson<null>(`/plans/${planId}`, { method: 'DELETE' })
}

export function listPlanTemplates(planId: number) {
  return requestJson<PlanTemplateVersion[]>(`/plans/${planId}/templates`)
}

export function createPlanTemplate(planId: number, payload: PlanTemplatePayload) {
  return requestJson<PlanTemplateVersion>(`/plans/${planId}/templates`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listAllDeployments() {
  return requestJson<Deployment[]>('/deployments')
}

export function getDeployment(userId: number, deploymentId: string) {
  return requestJson<Deployment>(`/users/${userId}/deployments/${deploymentId}`)
}

export function getDeploymentSftp(userId: number, deploymentId: string) {
  return requestJson<SftpCredentials>(`/users/${userId}/deployments/${deploymentId}/sftp`)
}

export function getDeploymentDatabase(userId: number, deploymentId: string) {
  return requestJson<DeploymentDatabase>(
    `/users/${userId}/deployments/${deploymentId}/database`,
  )
}

export function listDeployments(userId: number) {
  return requestJson<Deployment[]>(`/users/${userId}/deployments`)
}

export function createDeployment(
  userId: number,
  payload: {
    desired_template_id: number
    user_values_json?: object
    plan_template_id?: number
    vars?: Record<string, VarWrite>
  },
) {
  return requestJson<DeploymentCreateResponse>(`/users/${userId}/deployments`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateDeployment(
  userId: number,
  deploymentId: string,
  payload: {
    desired_template_id: number
    user_values_json?: object
    // Passed through explicitly: an update that omits it drops the release's
    // link to the build that produced the running image.
    build_id?: string | null
    vars?: Record<string, VarWrite>
  },
) {
  return requestJson<Deployment>(`/users/${userId}/deployments/${deploymentId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function deleteDeployment(userId: number, deploymentId: string) {
  return requestJson<null>(`/users/${userId}/deployments/${deploymentId}`, {
    method: 'DELETE',
  })
}

export function checkHostname(fqdn: string) {
  return requestJson<HostnameCheckResult>(`/hostnames/${encodeURIComponent(fqdn)}`)
}

export function getCnameTarget() {
  return requestJson<string>('/cname-target')
}

export function listSshKeys(userId: number) {
  return requestJson<SshKey[]>(`/users/${userId}/ssh-keys`)
}

export function addSshKey(userId: number, payload: { public_key: string; label?: string }) {
  return requestJson<SshKey>(`/users/${userId}/ssh-keys`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/**
 * Revoke one key. The fingerprint is encoded rather than interpolated raw:
 * it is unpadded base64, so about half of all fingerprints contain a `/`.
 */
export function deleteSshKey(userId: number, fingerprint: string) {
  return requestJson<null>(
    `/users/${userId}/ssh-keys/${encodeURIComponent(fingerprint)}`,
    { method: 'DELETE' },
  )
}
