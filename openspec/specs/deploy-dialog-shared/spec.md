# deploy-dialog-shared Specification

## Purpose

Defines the shared `DeployDialogContent` component that renders the deploy
form for both the Dashboard's deploy dialog and the admin template preview.

## Requirements

### Requirement: Shared deploy dialog content component
The system SHALL provide a `DeployDialogContent` component that renders the deploy form UI (product header with icon and description, `UserValuesForm`, and action buttons) and accepts all data as props without performing any data fetching or mutations internally.

#### Scenario: Dashboard deploy usage
- **WHEN** the Dashboard renders `DeployDialog` for a product
- **THEN** it SHALL wrap `DeployDialogContent` in a MUI Dialog, fetch templates via React Query, and pass the canonical template's schema, defaults, and deploy handlers as props

#### Scenario: Admin preview usage
- **WHEN** the Admin page renders a deploy preview for a template being edited
- **THEN** it SHALL render `DeployDialogContent` inline (not in a Dialog), passing the schema directly from the editor state, with action buttons disabled or hidden

### Requirement: DeployDialogContent props interface
The `DeployDialogContent` component SHALL accept: product (for header display), `valuesSchemaJson`, an `onLaunch` callback (optional), an `onCancel` callback (optional), and a `disabled` boolean to control the Launch button state. When `onLaunch` is not provided, the Launch button SHALL not be rendered. The `DeployDialogContent` component MUST NOT accept a `defaultValuesJson` prop. Callers that previously passed `defaultValuesJson` MUST stop passing it.

#### Scenario: Launch button visibility
- **WHEN** `onLaunch` is not provided
- **THEN** the Launch button SHALL not be rendered

#### Scenario: Cancel button visibility
- **WHEN** `onCancel` is not provided
- **THEN** the Cancel button SHALL not be rendered

### Requirement: Backward compatibility
The refactored `DeployDialog` on the Dashboard SHALL maintain identical behavior to the current implementation: fetching templates, finding the canonical template, creating deployments, hostname validation gating, and error display.

#### Scenario: Existing deploy flow unchanged
- **WHEN** a user clicks a product on the Dashboard and fills out the deploy form
- **THEN** the deploy flow SHALL work identically to before the refactor

### Requirement: DeployDialogContent accepts initialHostname and configurable button text
The `DeployDialogContent` component MUST accept an optional `initialHostname` prop that is threaded through `UserValuesForm` to `HostnameField`, and an optional `submitLabel` prop (default: `"Launch"`) to configure the submit button text.

#### Scenario: Initial hostname is prefilled
- **WHEN** `DeployDialogContent` is rendered with an `initialHostname`
- **THEN** the hostname field starts with that value

#### Scenario: Submit label defaults to Launch
- **WHEN** `DeployDialogContent` is rendered without a `submitLabel`
- **THEN** the submit button reads "Launch"

#### Scenario: Custom submit label
- **WHEN** `DeployDialogContent` is rendered with `submitLabel` "Save"
- **THEN** the submit button reads "Save"
