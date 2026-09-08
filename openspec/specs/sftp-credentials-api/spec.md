## Purpose

Users need to discover the connection details for their deployment's read-only file access. This capability exposes a deployment-scoped API endpoint (with matching CLI command) that returns the SFTP host, port and username for a deployment, and how the caller authenticates. It returns no credential and reads no Secret: access is authenticated by a public key registered on the owning account. The endpoint distinguishes deployments that have no file access from transient errors, and enforces the platform's standard deployment authorization rules.

## Requirements

### Requirement: Absence semantics for deployments without SSH access
The endpoint MUST distinguish "this deployment has no SSH access" from transient errors, returning a stable not-found response the UI can use to hide the feature.

Availability MUST be determined by what a deployment's chart actually renders, and the platform MUST NOT decide it by a marker that only one access profile emits. Both profiles grant SSH access and both are addressed through the same endpoint; a check written against the older profile's marker reports "no access" for every deployment on the newer one, which is a false negative in the one direction nobody notices — the feature simply disappears from the interface, while SSH itself keeps working because the edge resolves connections from the platform's records rather than from cluster labels.

#### Scenario: Product with no SSH access
- **WHEN** the owner requests details for a deployment whose chart renders no SSH resources
- **THEN** the API responds with 404 and a stable error body indicating SSH access is not available for this deployment

#### Scenario: Deployment on either profile reports available
- **WHEN** the owner requests details for a deployment on the `sftp` profile, and for one on the `dev` profile
- **THEN** both report the deployment's access details rather than a not-found

#### Scenario: Availability tracks what the chart renders
- **WHEN** the chart changes which marker it applies to a deployment's SSH resources
- **THEN** the platform's availability check follows it, rather than silently reporting no access

### Requirement: Authorization matches deployment access rules
Access to SFTP details MUST follow the existing deployment authorization model: the owning user and admins MAY read them; other users MUST be denied with the same status codes used by other deployment sub-resources.

#### Scenario: Non-owner is denied
- **WHEN** an authenticated user requests SFTP details of another user's deployment
- **THEN** the request is denied with the platform's standard authorization error

### Requirement: CLI parity
The Typer CLI MUST offer a command functionally identical to the endpoint (same authorization, same data, same absence semantics), consistent with the API/CLI parity convention.

#### Scenario: CLI retrieves connection details
- **WHEN** an operator runs the SFTP details CLI command for a deployment
- **THEN** the output contains the same host, port and username as the REST endpoint, and no credential

### Requirement: Deployment-scoped endpoint returns SFTP connection details without a password
The API MUST provide a read endpoint under the deployment resource (`GET /users/{user_id}/deployments/{deployment_id}/sftp`) returning the SFTP host and port for the environment (`freepod.eu:22` in prod, `dev.freepod.eu:23` in dev), plus the username for that deployment. Host and port MUST come from per-environment configuration (pydantic-settings) and MUST be the user-facing router values, not the internal HAProxy/cluster ports (2222/2223).

The username reported MUST be the deployment's id — the same identifier the SSH edge matches a connection on. Reporting anything else would hand the caller a username the edge refuses, so this endpoint and the resolver MUST NOT be able to disagree about what a deployment is addressed by.

The endpoint MUST NOT return a password. Access is authenticated by a public key registered on the owning account, and no per-deployment password exists to return. Serving the response MUST NOT require reading any Secret from the deployment's namespace, because nothing in the response is a credential.

The response MUST make clear how the caller authenticates, so that a client or a person reading it is not left to infer that a credential is missing. It MUST be possible to tell from the response whether the owning account has any registered key at all, since an account with none cannot connect and that is the single most likely reason a connection will fail.

#### Scenario: Owner retrieves connection details
- **WHEN** the owning user requests the SFTP details of a ready deployment whose product exposes files
- **THEN** the response contains the environment's configured host and port and the deployment's id as the username, and no password

#### Scenario: The reported username is what the edge accepts
- **WHEN** a caller connects using exactly the username this endpoint reported, offering a registered key
- **THEN** the edge admits the connection

#### Scenario: Response indicates key-based authentication
- **WHEN** the owner reads the response
- **THEN** it conveys that authentication uses a public key registered on the account

#### Scenario: Account with no registered key is identifiable
- **WHEN** the owning account has no registered SSH key
- **THEN** the response makes that determinable, so a client can explain why a connection would fail

#### Scenario: No credential is disclosed to anyone
- **WHEN** any caller, including an administrator, reads the response
- **THEN** it contains no credential material
