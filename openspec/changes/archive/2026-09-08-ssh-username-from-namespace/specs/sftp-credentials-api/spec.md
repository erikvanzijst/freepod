## MODIFIED Requirements

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
