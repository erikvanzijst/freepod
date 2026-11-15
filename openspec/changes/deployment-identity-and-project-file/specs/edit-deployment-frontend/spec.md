# Spec Delta

## ADDED Requirements

### Requirement: Settings edits the deployment's name, description and icon

The edit-mode dialog SHALL show the deployment's name, description and icon above its
chart values. An icon left unset SHALL show the product's, marked as the default. Saving
SHALL send them in the same update as the chart values, and SHALL leave out an icon the
owner did not change. A `name_in_use` refusal SHALL be shown on the name field.

#### Scenario: Renaming from the dashboard

- **WHEN** the owner changes only the name in Settings and saves
- **THEN** one update carrying the new name is sent, the row shows the new name, and no release is created

#### Scenario: Resetting the icon

- **WHEN** the owner removes a deployment's own icon
- **THEN** the update carries a null icon, and the product's icon is shown again

#### Scenario: A name in use

- **WHEN** the owner saves a name another of their deployments has
- **THEN** the name field shows that the name is in use, and nothing is saved

### Requirement: Managed fields are read-only and say where they are managed

Every field whose key is among the deployment's managed fields SHALL be shown read-only,
marked as managed by `.freepod.json`. A managed value SHALL be sent unchanged on update,
and the update SHALL carry no `managed_fields`.

#### Scenario: A managed sign-in setting

- **WHEN** `auth` is managed and the owner opens Settings
- **THEN** the Sign in with Freepod fields are read-only and marked as managed by `.freepod.json`

#### Scenario: Updating around a managed field

- **WHEN** `auth` is managed and the owner changes another chart value and saves
- **THEN** the update carries `auth` exactly as the deployment has it

### Requirement: A managed field can be taken over from the dashboard

Each managed field SHALL offer Take over. On confirmation it SHALL send an update whose
`managed_fields` is the current list without that key, and make the field editable. The
confirmation SHALL warn that the next `freepod apply` or deploy from a file still holding
the key sets it back.

#### Scenario: Taking over the name

- **WHEN** the owner confirms Take over on a managed name
- **THEN** an update with the managed fields minus `name` is sent, and the name field becomes editable
