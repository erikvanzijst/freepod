# deployment-naming Specification

## Purpose

Every deployment is given a generated release name, which is the name of its Helm release. This capability defines how that name is generated and stored, and how its uniqueness follows from the namespace rather than from a constraint of its own.

## Requirements

### Requirement: Deployment name generation
The system MUST generate a release name for each new deployment using the formula `"{slugify(product_name)[:20]}-{random6}"`, where `slugify` lowercases, replaces non-alphanumeric characters with hyphens, collapses consecutive hyphens, and strips leading/trailing hyphens. The truncation to 20 characters MUST strip any resulting trailing hyphens. The random suffix MUST be 6 base36 characters (`[0-9a-z]{6}`).

#### Scenario: Name generated from normal product name
- **WHEN** a deployment is created for a product named `Hello Static`
- **THEN** the name starts with `hello-static-` followed by a 6-character random suffix
- **AND** the total name length MUST NOT exceed 27 characters

#### Scenario: Name generated from long product name
- **WHEN** a deployment is created for a product with a name longer than 20 characters after slugification
- **THEN** the product slug is truncated to at most 20 characters before appending the random suffix
- **AND** the truncation MUST NOT leave a trailing hyphen

#### Scenario: Name generated from product name with special characters
- **WHEN** a deployment is created for a product named `My App (v2.0)!!!`
- **THEN** non-alphanumeric characters are replaced with hyphens, consecutive hyphens are collapsed, and leading/trailing hyphens are stripped before truncation

#### Scenario: Generated name is a valid DNS label
- **WHEN** any deployment name is generated
- **THEN** it MUST be a valid DNS label: lowercase alphanumeric and hyphens only, starting and ending with an alphanumeric character, at most 63 characters

#### Scenario: Fallback when product name has no alphanumeric characters
- **WHEN** a deployment is created for a product whose name contains only non-alphanumeric characters
- **THEN** the system MUST use a fallback base (e.g., `dep`) before appending the random suffix

### Requirement: Column rename from deployment_uid to name
The `deployment_uid` column on the `deployment` table MUST be renamed to `name`. All code, schemas, API responses, and TypeScript types MUST reference `name` instead of `deployment_uid`.

#### Scenario: API response uses name field
- **WHEN** a client reads a deployment via the API
- **THEN** the response includes a `name` field (not `deployment_uid`)

#### Scenario: ORM model uses name field
- **WHEN** application code accesses the deployment's release name
- **THEN** it uses `deployment.name` (not `deployment.deployment_uid`)

### Requirement: Deployment name is persisted and immutable
The system MUST store the generated name in the `name` column of the `deployment` table. The name MUST be set at deployment creation time and MUST NOT be modified after creation.

#### Scenario: Name persisted on create
- **WHEN** a new deployment is created
- **THEN** the `name` column is populated with the generated name value

#### Scenario: Name not modified on update
- **WHEN** a deployment is updated
- **THEN** the `name` column value MUST remain unchanged

### Requirement: Name used as Helm release name
The reconciler MUST use the deployment's `name` field as the Helm release name when provisioning, updating, or deleting the deployment.

#### Scenario: Reconciler uses name for helm install
- **WHEN** the reconciler applies a deployment
- **THEN** it passes `release_name=deployment.name` to `helm_upgrade_install`

#### Scenario: Reconciler uses name for helm uninstall
- **WHEN** the reconciler deletes a deployment
- **THEN** it passes `release_name=deployment.name` to `helm_uninstall`

### Requirement: Max name length provides sufficient headroom
The deployment name MUST NOT exceed 27 characters, leaving at least 36 characters of headroom within the 63-character DNS label limit for chart resource suffixes and Kubernetes-generated hash labels.

#### Scenario: Name length within budget
- **WHEN** any deployment name is generated
- **THEN** its length MUST be at most 27 characters

### Requirement: The deployment name is unique within its namespace as a consequence
A deployment's name MUST be unique within its namespace, so that it is unambiguous as a Helm release name and as the account the SSH edge presents to that deployment's sidecar. This MUST follow from the namespace being unique per deployment rather than from a constraint on the pair.

The name MUST NOT be relied on as a globally unique identifier. It is generated from the product name and a 6-character random suffix, and nothing enforces uniqueness across namespaces; a component that selects a deployment by name alone can select the wrong one.

#### Scenario: One release per namespace
- **WHEN** a deployment's namespace is inspected
- **THEN** it contains exactly one deployment's Helm release, so the name within it names one thing

#### Scenario: The same name in two namespaces is permitted
- **WHEN** two deployments of the same product are created and receive the same generated name
- **THEN** both are accepted, because they occupy different namespaces

#### Scenario: Nothing addresses a deployment by name alone
- **WHEN** a component resolves which deployment to act on from an externally supplied identifier
- **THEN** it MUST use the namespace, not the name
