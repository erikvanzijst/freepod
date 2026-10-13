## MODIFIED Requirements

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
