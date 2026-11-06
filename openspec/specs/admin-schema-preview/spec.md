# admin-schema-preview Specification

## Purpose
Defines the admin's "New" template tab: a schema editor with a live preview of the
deploy dialog the schema produces, and the guards on saving a new template version.

## Requirements

### Requirement: Schema editor with live validation indicator
The "New" template tab SHALL include a Monaco editor for the user values JSON schema. A validation indicator SHALL be displayed near the editor showing the current validity state: a green tick when the editor contents are valid JSON, and a red exclamation mark when they are not.

#### Scenario: Valid JSON in editor
- **WHEN** the schema editor contains valid JSON
- **THEN** a green tick indicator SHALL be displayed near the editor

#### Scenario: Invalid JSON in editor
- **WHEN** the schema editor contains invalid JSON (e.g., during typing)
- **THEN** a red exclamation mark indicator SHALL be displayed near the editor

### Requirement: Live deploy dialog preview
The "New" template tab SHALL display a live preview of the deploy dialog alongside the schema editor. The preview SHALL render using the same `DeployDialogContent` component used on the Dashboard, with action buttons not rendered. The preview SHALL update in real-time (with debouncing) as the admin edits the schema.

#### Scenario: Preview updates on valid schema change
- **WHEN** the admin modifies the schema editor to contain valid JSON
- **THEN** the deploy dialog preview SHALL update to reflect the new schema after a debounce period

#### Scenario: Preview freezes on invalid schema
- **WHEN** the admin's edits result in invalid JSON in the schema editor
- **THEN** the deploy dialog preview SHALL continue showing the last valid schema

### Requirement: Save button gated on validity
The Save/Add button for creating a new template SHALL be disabled whenever the schema editor contains invalid JSON.

#### Scenario: Save disabled on invalid JSON
- **WHEN** the schema editor contains invalid JSON
- **THEN** the Save/Add button SHALL be disabled

#### Scenario: Save enabled on valid JSON
- **WHEN** the schema editor contains valid JSON and all required fields (chart ref, chart version) are filled
- **THEN** the Save/Add button SHALL be enabled

### Requirement: New tab pre-population
When the "New" tab is selected, its form fields SHALL be pre-populated from the newest existing template version (by creation date). If no templates exist, the schema editor SHALL be pre-populated with a bare-bones default schema (`DEFAULT_VALUES_SCHEMA`), and other fields SHALL start empty.

#### Scenario: Pre-populate from newest template
- **WHEN** a product has existing templates and the admin selects the "New" tab
- **THEN** the chart ref, chart version, schema, and defaults SHALL be copied from the newest template

#### Scenario: No existing templates
- **WHEN** a product has no templates and the admin selects the "New" tab
- **THEN** the schema editor SHALL contain the default bare-bones schema and chart ref/version fields SHALL be empty

### Requirement: Defaults editor below preview
The "New" template tab SHALL include a Monaco editor for the template's `default_values_json` below the schema editor and preview area. This editor SHALL also validate that its contents are valid JSON before allowing save.

#### Scenario: Editing defaults
- **WHEN** the admin types in the defaults editor
- **THEN** the contents SHALL be used as `default_values_json` when saving the new template

#### Scenario: Invalid defaults JSON
- **WHEN** the defaults editor contains invalid JSON
- **THEN** the Save/Add button SHALL be disabled

### Requirement: Template editors use system_values_json
The admin template UI MUST use the label "System values" instead of "Default values" for the system values Monaco editor. The `onSave` payload MUST use the field name `system_values_json` instead of `default_values_json`. The deploy dialog preview in both `TemplateTabNew` and `TemplateTabReadOnly` MUST NOT pass system values to `DeployDialogContent` (it no longer accepts the prop).

#### Scenario: Saving a new template
- **WHEN** the admin saves a new template version
- **THEN** the system values editor is labeled "System values" and the payload carries
  them as `system_values_json`

### Requirement: The preview reflects the schema's conditionals
The live deploy dialog preview SHALL show, hide and require fields by the
conditionals of the schema in the editor, as the deploy form does. It SHALL re-evaluate
them whenever the editor holds a new valid schema and whenever the admin changes a
field in the preview.

#### Scenario: A conditional added in the editor
- **WHEN** the admin adds a root `if`/`then` whose `then` requires a field, and the
  condition does not hold for the preview's values
- **THEN** after the debounce period the preview no longer shows that field

#### Scenario: A toggle in the preview
- **WHEN** the admin changes a preview field so that the condition holds
- **THEN** the field appears, marked required

#### Scenario: The conditional removed again
- **WHEN** the admin removes the `if`/`then` from the editor
- **THEN** the field is shown and no longer marked required
