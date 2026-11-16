# Spec Delta

## Purpose

What the platform knows of a project file: the top-level keys it reserves, the fields a
file claims as managed and how they are protected from other writes, and the JSON Schema
it publishes per product for the file.

## ADDED Requirements

### Requirement: Reserved keys cannot be template properties

A template whose value schema declares a top-level property named `name`,
`description`, `icon`, `tags`, `$schema`, `version`, `env` or `deployment` SHALL be
refused at creation. Catalog lint SHALL report the same.

#### Scenario: A template declaring `name`

- **WHEN** an administrator creates a template whose value schema declares a top-level `name` property
- **THEN** the template is refused and names the reserved key

#### Scenario: A nested `name` is allowed

- **WHEN** a value schema declares `admin.name`
- **THEN** the template is accepted

### Requirement: A request that names managed fields sets them

A deployment create or update MAY carry `managed_fields`, a list of top-level keys:
`name`, `description`, `icon`, or top-level properties of the template's chart
projection. A request that carries it SHALL set the deployment's managed fields to
exactly that list, and MAY change any field. A key that is neither SHALL be refused with
`400`. Deployment reads SHALL report `managed_fields`, empty where none are managed.

#### Scenario: Claiming fields

- **WHEN** an update carries `managed_fields` of `["name", "auth"]`
- **THEN** the deployment's managed fields are `name` and `auth`

#### Scenario: Giving a field up

- **WHEN** a later update carries `managed_fields` of `["name"]`
- **THEN** only `name` is managed, and `auth` keeps its value

#### Scenario: A key no template declares

- **WHEN** an update carries `managed_fields` holding `auht` on a Custom deployment
- **THEN** it is refused with `400` and nothing is changed

### Requirement: A managed field is changed only by a request that names managed fields

A create or update that carries no `managed_fields` SHALL be refused with `409` and code
`managed_by_project_file`, naming the field, when it would change the value of a managed
field. This SHALL hold for the owner, an administrator and the operator CLI alike. Such
a request that leaves every managed value as it is SHALL proceed.

#### Scenario: Renaming a managed name in the dashboard

- **WHEN** a deployment's `name` is managed and an update without `managed_fields` carries a new name
- **THEN** the request is refused with `409` and code `managed_by_project_file`

#### Scenario: Updating around a managed field

- **WHEN** `auth` is managed and an update without `managed_fields` changes only `hostname`, carrying `auth` unchanged
- **THEN** the update is accepted

### Requirement: A managed field can be taken over

Taking over a managed field SHALL be an update whose `managed_fields` is the current list
without that key. The key's value SHALL be unchanged by it. If a later update names the
key in its `managed_fields` again, the key SHALL be managed again and take that request's
value.

#### Scenario: Taking over the description

- **WHEN** the owner sends an update with the current managed fields minus `description`
- **THEN** `description` is no longer managed and keeps its value

#### Scenario: The file claims it back

- **WHEN** a later update carries a description and names `description` in its managed fields
- **THEN** `description` is managed again and set to that value

### Requirement: Each product publishes the JSON Schema of its project file

`GET /api/products/{slug}/project-schema` SHALL return, without authentication, a JSON
Schema 2020-12 document for that product's project file, built from its canonical
template. It SHALL describe the file's own keys, the metadata keys and the product's
chart properties, and SHALL refuse every other key.

#### Scenario: The Custom schema

- **WHEN** an editor fetches `/api/products/custom/project-schema`
- **THEN** the schema describes `auth` with its `enabled`, `access` and `public` properties

#### Scenario: An unknown product

- **WHEN** the slug names no visible product
- **THEN** the response is `404`
