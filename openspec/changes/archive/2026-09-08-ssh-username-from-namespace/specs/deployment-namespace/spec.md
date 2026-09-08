## MODIFIED Requirements

### Requirement: Deployment namespace generation
The system MUST generate a namespace identifier for each new deployment using the formula `"{slugify(product_name)[:20]}-{slugify(email_local_part)[:10]}-{random9}"`, where `email_local_part` is the portion of the owner's email address before the first `@`, and `slugify` lowercases, replaces non-alphanumeric characters with hyphens, collapses consecutive hyphens, and strips leading/trailing hyphens. Each truncation MUST strip any resulting trailing hyphens. The random suffix MUST be 9 base36 characters (`[0-9a-z]{9}`). A segment that slugifies to nothing MUST fall back to a fixed non-empty token, so the result is always a valid DNS label.

The namespace MUST NOT contain the owner's email domain. It carries a product segment and an owner segment because an operator reading a list of namespaces needs to know what each one holds and whose it is; that is the whole of what it is for, and a full email address is more than that question requires.

#### Scenario: Namespace generated from product and email
- **WHEN** a deployment of the product `Hello Static` is created for a user with email `alice.smith@example.com`
- **THEN** the namespace begins with a slugified product prefix, followed by a slugified prefix of `alice.smith`, followed by a 9-character random suffix
- **AND** it contains no part of the email domain
- **AND** the total namespace length MUST NOT exceed 41 characters

#### Scenario: Namespace generated from long product name and long email
- **WHEN** a deployment is created whose product name slugifies to more than 20 characters and whose owner's email local part slugifies to more than 10
- **THEN** the product segment is truncated to at most 20 characters and the email segment to at most 10 before the random suffix is appended
- **AND** neither truncation leaves a trailing hyphen

#### Scenario: Namespace generated from email with special characters
- **WHEN** a deployment is created for a user whose email local part contains `+`, `.`, or other non-alphanumeric characters
- **THEN** those characters are replaced with hyphens, consecutive hyphens are collapsed, and leading/trailing hyphens are stripped before truncation

#### Scenario: A segment with no alphanumeric characters falls back
- **WHEN** a deployment is created whose product name or whose email local part contains no alphanumeric character
- **THEN** that segment is replaced by a fixed fallback token rather than producing an empty segment or a doubled hyphen

#### Scenario: Generated namespace is a valid DNS label
- **WHEN** any namespace is generated
- **THEN** it MUST be a valid DNS label: lowercase alphanumeric and hyphens only, starting and ending with an alphanumeric character, at most 63 characters

### Requirement: Deployment namespace is persisted and immutable
The system MUST store the generated namespace in the `namespace` column of the `deployment` table. The namespace MUST be set at deployment creation time and MUST NOT be modified after creation.

The namespace names a live Kubernetes namespace, so changing it would orphan every object inside it. No API, CLI command, or administrative path MUST offer to change it, and a deployment created under an earlier form of the generation formula MUST keep the namespace it was given.

#### Scenario: Namespace persisted on create
- **WHEN** a new deployment is created
- **THEN** the `namespace` column is populated with the generated namespace value

#### Scenario: Namespace not modified on update
- **WHEN** a deployment is updated (e.g., template change, user values change)
- **THEN** the `namespace` column value MUST remain unchanged

#### Scenario: A namespace predating a formula change is left alone
- **WHEN** the generation formula changes and an existing deployment is read or reconciled
- **THEN** its namespace is unchanged and no migration rewrites it

## ADDED Requirements

### Requirement: A namespace belongs to one deployment, for good
The database MUST enforce that no two deployment rows share a `namespace`, with no predicate excluding any status. Uniqueness MUST hold across deleted deployments as well as active ones.

A namespace is a Kubernetes namespace, and two deployments sharing one would put two tenants' workloads in the same isolation boundary — the boundary the platform relies on to keep them apart. Deleted rows are included because namespace deletion is asynchronous: a namespace whose row is marked deleted may still be terminating in the cluster, and a second deployment claiming it would race that teardown.

#### Scenario: Two deployments cannot share a namespace
- **WHEN** a deployment exists with a given namespace and another row is written with the same namespace
- **THEN** the database MUST reject the write with an integrity error

#### Scenario: A deleted deployment still holds its namespace
- **WHEN** a deployment is deleted and a new deployment is written with that namespace
- **THEN** the database MUST reject the write

#### Scenario: Existing rows are verified before the constraint is applied
- **WHEN** the constraint is introduced on a database whose rows already violate it
- **THEN** the migration MUST fail with a message naming the duplicate namespaces, rather than surfacing an opaque index-creation error

### Requirement: A namespace collision is resolved at creation, not surfaced
Deployment creation MUST NOT fail because a generated namespace was already taken. The system MUST detect that a candidate namespace is in use and generate another, up to a bounded number of attempts, before the deployment is written.

The generator draws a random suffix and does not consult existing rows, so a collision is possible however unlikely; the uniqueness constraint is the guarantee, and regeneration is what keeps that guarantee from being paid for by the user whose creation happened to collide. Exhausting the bounded attempts MUST be reported as a platform error, never resolved by weakening the constraint or by writing a duplicate.

#### Scenario: A colliding candidate is regenerated
- **WHEN** a generated namespace matches one already recorded, for a deleted or an active deployment
- **THEN** another namespace is generated and the deployment is created successfully with it

#### Scenario: A user never sees a collision
- **WHEN** a deployment is created and the first candidate namespace collides
- **THEN** the request succeeds and the response reports the namespace actually assigned

#### Scenario: Exhausted attempts fail loudly
- **WHEN** the bounded number of attempts is exhausted without a free namespace
- **THEN** creation fails with a platform error and no deployment row is written

### Requirement: The namespace is internal and is not published as an address
The namespace MUST NOT be the identifier by which anything outside the platform addresses a deployment. No API response, client command, or user-facing document MUST present it as a value a user is expected to type or keep.

It describes where a deployment runs, which is infrastructure the platform must stay free to change. An external caller holding it would make the layout of the cluster a compatibility surface, so that renaming, re-shaping, or re-pooling namespaces could not be done without breaking that caller.

#### Scenario: The namespace is not an SSH username
- **WHEN** a client presents a deployment's namespace as its SSH username
- **THEN** the connection is refused, because the namespace addresses nothing at the edge

#### Scenario: Changing how namespaces are generated breaks no caller
- **WHEN** the generation formula changes
- **THEN** no external contract changes with it, because nothing outside the platform addresses a deployment by its namespace
