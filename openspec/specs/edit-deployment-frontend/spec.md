# edit-deployment-frontend Specification

## Purpose

Lets a user change a deployment's settings from the dashboard, through the
deploy dialog in edit mode, which pre-fills the deployment's current values and
submits them to the update endpoint.

## Requirements

### Requirement: Deployment rows offer Settings for running and failed deployments
The Dashboard MUST offer a Settings action in the expanded view of each
deployment row whose status is `ready` or `error`, and MUST NOT offer it in
any other status. Selecting it MUST open the `DeployDialog` in edit mode for
that deployment.

#### Scenario: Settings offered on a running deployment
- **WHEN** a deployment's status is `ready` and its row is expanded
- **THEN** the row offers Settings alongside its access actions and Remove app

#### Scenario: Settings offered on a failed deployment
- **WHEN** a deployment's status is `error` and its row is expanded
- **THEN** the row offers Settings, so that the settings can be saved again

#### Scenario: Settings hidden during provisioning
- **WHEN** a deployment's status is `provisioning`
- **THEN** its row does not offer Settings

#### Scenario: Settings opens DeployDialog in edit mode
- **WHEN** the user selects Settings on a deployment row
- **THEN** the `DeployDialog` opens with the deployment's product, current
  `user_values_json` pre-populated in the form, and submit wired to the update
  endpoint

### Requirement: DeployDialog supports edit mode
The `DeployDialog` component MUST accept an optional `deployment` prop. When `deployment` is provided, the dialog operates in edit mode:
1. The form is pre-populated with `deployment.user_values_json`
2. On submit, the dialog calls `PUT /api/users/{user_id}/deployments/{deployment_id}` instead of `POST /api/users/{user_id}/deployments`
3. The submit button text reads "Update" instead of "Launch"
4. The deployment's current `hostname` is passed as `initialHostname` to the hostname field

#### Scenario: Edit dialog pre-populates existing values
- **WHEN** the DeployDialog opens in edit mode for a deployment with `user_values_json: {"ingress": {"hostname": "my.app"}, "settings": {"theme": "dark"}}`
- **THEN** the form fields show `my.app` in the hostname field and `dark` in the theme field

#### Scenario: Edit dialog submits via PUT
- **WHEN** the user modifies values in edit mode and clicks Update
- **THEN** the dialog calls `PUT /api/users/{user_id}/deployments/{deployment_id}` with the deployment's current `desired_template_id` and the modified `user_values_json`

#### Scenario: Create dialog behavior unchanged
- **WHEN** the DeployDialog is opened without a `deployment` prop
- **THEN** it behaves identically to the current implementation (empty form, POST on submit, "Launch" button)

#### Scenario: Edit dialog handles 409 Conflict
- **WHEN** the update request returns HTTP 409 (deployment not in ready state)
- **THEN** the dialog displays an error message indicating the deployment cannot be updated in its current state

### Requirement: DeployDialog create mode sends empty object when no values entered
In create mode, when the user does not enter any custom values, the `DeployDialog` MUST send `{}` (empty object) as `user_values_json` instead of falling back to `default_values_json`. The reconciler's merge chain applies template defaults as the base layer regardless.

#### Scenario: Create with no user input sends empty values
- **WHEN** the user opens the deploy dialog and clicks Launch without entering any values
- **THEN** the request payload contains `user_values_json: {}` (not the template's `default_values_json`)

### Requirement: updateDeployment frontend API endpoint
The frontend API layer MUST provide an `updateDeployment(userId, deploymentId, payload)` function that sends a `PUT /api/users/{user_id}/deployments/{deployment_id}` request with the given payload.

#### Scenario: Update deployment API call
- **WHEN** `updateDeployment(1, 42, { desired_template_id: 5, user_values_json: {...} })` is called
- **THEN** a PUT request is sent to `/api/users/1/deployments/42` with the payload
