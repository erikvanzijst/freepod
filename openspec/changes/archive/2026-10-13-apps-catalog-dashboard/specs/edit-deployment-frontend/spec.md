## REMOVED Requirements

### Requirement: Dashboard shows Edit button on deployment cards
**Reason**: Deployment cards are replaced by expandable rows, and a deployment
in `error` now offers its settings, since saving them again is the first
remedy its notice suggests.
**Migration**: Replaced by "Deployment rows offer Settings for running and
failed deployments".

## ADDED Requirements

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
