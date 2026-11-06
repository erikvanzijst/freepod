# deploy-dialog-shared Specification

## Purpose

Defines the shared `DeployDialogContent` component that renders the deploy
form for both the Dashboard's deploy dialog and the admin template preview.

## Requirements

### Requirement: Shared deploy dialog content component
The system SHALL provide a `DeployDialogContent` component that renders the deploy form UI (product header with icon and tagline, `UserValuesForm`, and action buttons) and accepts all data as props without performing any data fetching or mutations internally. The header SHALL omit the tagline line when the product has none, and SHALL NOT show the product's long `description`.

#### Scenario: Dashboard deploy usage
- **WHEN** the Dashboard renders `DeployDialog` for a product
- **THEN** it SHALL wrap `DeployDialogContent` in a MUI Dialog, fetch templates via React Query, and pass the canonical template's schema, defaults, and deploy handlers as props

#### Scenario: Admin preview usage
- **WHEN** the Admin page renders a deploy preview for a template being edited
- **THEN** it SHALL render `DeployDialogContent` inline (not in a Dialog), passing the schema directly from the editor state, with action buttons disabled or hidden

#### Scenario: Header shows the tagline
- **WHEN** the dialog renders a product whose tagline is "Your photos and videos, backed up from your phone and kept private."
- **THEN** that sentence appears under the product name

#### Scenario: Product without a tagline
- **WHEN** the dialog renders a product with no tagline
- **THEN** no subtitle is shown and the long description is not shown either

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

### Requirement: The deploy form shows a conditional field only while its branch applies
The deploy form SHALL read `if`/`then`/`else`, the same inside `allOf` entries, and
`dependentRequired`, both at the schema's root and inside every object property. An
object property's conditionals SHALL be evaluated against that object's value, an
absent one as empty. A property a branch mentions, in its `required` or `properties`,
SHALL be shown only while such a branch applies, unless its object's `required` names
it. A property no branch mentions SHALL always be shown. A hidden object property SHALL
hide every field under it. A `dependentRequired` entry SHALL apply while its trigger
is present.

#### Scenario: Sign-in on hides the admin password
- **WHEN** a schema declares the chart value `auth.enabled` (default `true`) and the
  sensitive var `NEXTCLOUD_ADMIN_PASSWORD`, with a root `if` on `auth.enabled` being
  `false` whose `then` requires `NEXTCLOUD_ADMIN_PASSWORD`
- **AND** the form renders with the checkbox checked
- **THEN** the password field is not shown

#### Scenario: Sign-in off shows it
- **WHEN** the user unchecks the checkbox
- **THEN** the password field appears, marked required
- **AND** re-checking the checkbox hides it again

#### Scenario: A property its object requires
- **WHEN** a branch mentions a property its object's `required` names
- **THEN** the field is shown whether or not the branch applies

#### Scenario: Sign-in settings inside the auth object
- **WHEN** the object property `auth` declares `enabled`, `access` and `public`, with
  an `if` requiring `enabled` to be `true` whose `then` declares `access` and `public`
- **AND** the form renders with the checkbox unchecked
- **THEN** neither the access nor the public paths field is shown
- **AND** checking the checkbox shows both

### Requirement: Conditions are evaluated against the document a submission would form
The form SHALL evaluate each `if` with the JSON Schema validator it uses for
client-side validation, against one document holding the chart values and the vars it
would submit, vars typed as the platform coerces them. A field SHALL be marked required
when its object's `required` or an applying branch's `required` names it.

#### Scenario: A boolean var read by a condition
- **WHEN** an `if` requires the boolean var `SIGNUPS` to be `true`
- **AND** the user checks the `SIGNUPS` field
- **THEN** the condition holds, as it would for the platform's coerced value

### Requirement: A hidden field's value is not submitted
A field the conditionals hide SHALL contribute nothing to the submission: no chart
value and no var entry. The form SHALL keep what the user typed, so showing the field
again restores it. A stored var whose field is hidden SHALL be left as stored, never
deleted.

#### Scenario: A value typed before the field was hidden
- **WHEN** the user types a password, then checks the checkbox that hides its field
- **THEN** the submission carries no entry for the password

#### Scenario: A stored var in a hidden field
- **WHEN** the Edit dialog opens a deployment whose stored vars include one whose field
  is hidden
- **AND** the user submits the update
- **THEN** the update carries no entry for that var, and the stored var is unchanged
