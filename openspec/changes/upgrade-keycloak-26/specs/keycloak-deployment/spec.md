# Spec Delta

## MODIFIED Requirements

### Requirement: Keycloak data persists across restarts
Keycloak SHALL store all realm, client, user and sign-in session state in the PostgreSQL database, whose storage is backed by a PersistentVolumeClaim. The Keycloak pod itself is stateless and mounts no persistent volume.

#### Scenario: PVC exists for PostgreSQL
- **WHEN** `kubectl get pvc -n keycloak postgres-pvc` is executed
- **THEN** a PVC exists with a `1Gi` `ReadWriteOnce` request

#### Scenario: Sign-ins survive a Keycloak restart
- **WHEN** a user is signed in and the Keycloak pod is restarted
- **THEN** the user's SSO session is still valid afterwards
- **AND** the dashboard's next session refresh succeeds without a new sign-in

### Requirement: Keycloak is configured via environment variables
The system SHALL configure Keycloak with environment variables for its public URL, proxy header handling, database and bootstrap administrator, using only options the running Keycloak version supports. The public URL SHALL be pinned to `https://keycloak.freepod.eu`, so that the issuer and every URL Keycloak generates use it, however a request reached the server.

#### Scenario: Keycloak environment variables are set
- **WHEN** Keycloak pod spec is inspected
- **THEN** environment variables include `KC_HOSTNAME` set to `https://keycloak.freepod.eu`, `KC_PROXY_HEADERS` and `KC_DB`
- **AND** the bootstrap administrator is supplied through `KC_BOOTSTRAP_ADMIN_USERNAME` and `KC_BOOTSTRAP_ADMIN_PASSWORD`

#### Scenario: No removed or deprecated option is set
- **WHEN** Keycloak starts
- **THEN** no hostname v1 option (`KC_HOSTNAME_URL`, `KC_HOSTNAME_ADMIN_URL`, `KC_HOSTNAME_STRICT_BACKCHANNEL`), `KC_PROXY` or `KEYCLOAK_ADMIN*` variable is set

#### Scenario: The issuer is the public URL
- **WHEN** `https://keycloak.freepod.eu/realms/freepod/.well-known/openid-configuration` is requested
- **THEN** its `issuer` is `https://keycloak.freepod.eu/realms/freepod`

### Requirement: Keycloak has health checks
The system SHALL enable Keycloak's health endpoints and configure readiness and liveness probes against them, so that traffic reaches Keycloak only once it has finished starting, including any database migration.

#### Scenario: Keycloak probes are configured
- **WHEN** Keycloak deployment spec is inspected
- **THEN** both readinessProbe and livenessProbe are defined
- **AND** the readiness probe targets Keycloak's `/health/ready` endpoint

#### Scenario: No traffic before startup completes
- **WHEN** Keycloak has opened its HTTP port but has not finished bootstrapping
- **THEN** the pod is not Ready and the Service routes no requests to it

## ADDED Requirements

### Requirement: Keycloak runs a pinned version
The Keycloak image SHALL be built from an exact upstream release tag, so that the server version changes only through a reviewed change to this repository.

#### Scenario: Base image is pinned
- **WHEN** the Keycloak image's Dockerfile is inspected
- **THEN** its base image names a full `major.minor.patch` Keycloak release

### Requirement: Two Keycloak versions never share the database
The Keycloak deployment SHALL never run two pods against the database at once, so that a new version never migrates the schema while an older version is still serving from it. A Keycloak database migration cannot be reversed.

#### Scenario: Pod replacement does not overlap
- **WHEN** the Keycloak deployment's pod template changes
- **THEN** the old pod has terminated before the new pod starts

#### Scenario: Upgrades are preceded by a backup
- **WHEN** the Keycloak version is raised
- **THEN** a dump of the Keycloak database is taken before the new version first starts
- **AND** rolling back means restoring that dump with the previous image
