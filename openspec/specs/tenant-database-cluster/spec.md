# tenant-database-cluster Specification

## Purpose
The shared PostgreSQL server and connection pooler that hold every `custom` deployment's
database: how they are versioned, isolated from the control plane, authenticated,
bounded in resources, and what capacity limits they operate under on a single-node
cluster whose storage class enforces nothing.

## Requirements

### Requirement: The tenant cluster is separate from the control-plane database
Tenant databases SHALL be hosted on a PostgreSQL instance separate from the one holding
platform tables, and each Terraform workspace SHALL have its own tenant cluster.

#### Scenario: Control plane is unaffected by tenant load
- **WHEN** a tenant saturates the tenant cluster
- **THEN** the platform's own database is unaffected

#### Scenario: Environments do not share a cluster
- **WHEN** a deployment is provisioned in the development environment
- **THEN** its database is created on that environment's tenant cluster and not on production's

### Requirement: Applications reach the cluster only through the pooler
Tenant workloads SHALL connect through the pooler, and SHALL NOT be able to reach the
PostgreSQL server directly.

#### Scenario: Pooler is reachable
- **WHEN** a tenant pod connects to the pooler endpoint
- **THEN** the connection is permitted

#### Scenario: Direct PostgreSQL access is refused
- **WHEN** a tenant pod attempts to connect to the PostgreSQL server directly
- **THEN** the connection is denied by network policy

### Requirement: The pooler uses transaction pooling with prepared-statement support
The pooler SHALL use transaction pooling and SHALL support protocol-level prepared
statements, so that common drivers and ORMs work with their default settings.

#### Scenario: A default driver connects successfully
- **WHEN** an application connects using a driver that issues prepared statements by default
- **THEN** its queries succeed without the application disabling prepared statements

#### Scenario: Many clients share fewer server connections
- **WHEN** more client connections are open than server connections
- **THEN** clients are multiplexed over the server pool

### Requirement: Pooler authentication resolves against a database no tenant can reach
The pooler's authentication lookup SHALL be pinned to a database on the tenant cluster
that no tenant can connect to, so that no tenant can influence how credentials are
resolved. It SHALL NOT resolve against the control-plane database, so that a
control-plane outage cannot prevent tenants from authenticating to their databases.
The lookup SHALL answer for deployment roles only, so that no platform role can be
logged into through the pooler.

#### Scenario: Platform roles are not reachable through the pooler
- **WHEN** a client connects to the pooler as a platform role such as the superuser or the admin role
- **THEN** the pooler finds no credentials for it and refuses the login, whatever password is offered

#### Scenario: Lookup does not occur in a tenant database
- **WHEN** a tenant connects to their own database through the pooler
- **THEN** the credential lookup is performed against the pinned platform database, not the tenant's

#### Scenario: A tenant cannot define the lookup
- **WHEN** a tenant creates objects in their own database matching the lookup's names
- **THEN** authentication behavior is unaffected

#### Scenario: A tenant cannot reach the lookup database
- **WHEN** a deployment role attempts to connect to the database the lookup is pinned to
- **THEN** the connection is refused

#### Scenario: Tenant authentication survives a control-plane outage
- **WHEN** the control-plane database is unavailable
- **THEN** tenants can still authenticate to their own databases through the pooler

### Requirement: No platform process holds a pooler administrative credential
No platform process SHALL require or hold administrative access to the pooler. Every
operation the platform performs against a tenant's database SHALL be expressed against
PostgreSQL.

#### Scenario: Provisioning issues no pooler command
- **WHEN** a deployment is provisioned or removed
- **THEN** no administrative command is issued to any pooler instance

#### Scenario: Suspension issues no pooler command
- **WHEN** a deployment is suspended or restored
- **THEN** no administrative command is issued to any pooler instance

#### Scenario: Scaling the pooler needs no coordination
- **WHEN** the number of pooler instances changes
- **THEN** no platform process needs to be reconfigured for correctness

### Requirement: Runtime processes hold no superuser credential
Superuser access to the tenant cluster SHALL be used only by the one-time bootstrap.
Long-running platform processes SHALL operate under a non-superuser administrative role
holding only the privileges their operations require.

#### Scenario: Workers run without superuser
- **WHEN** the reconcile worker or the housekeeping worker connects to the tenant cluster
- **THEN** it authenticates as a non-superuser role

#### Scenario: The administrative role can still perform the full lifecycle
- **WHEN** the administrative role provisions, measures, degrades, suspends and purges a deployment's database
- **THEN** every operation succeeds without superuser

#### Scenario: The administrative role does not silently hold tenant privileges
- **WHEN** the administrative role is connected without having explicitly assumed a tenant role
- **THEN** it does not inherit that tenant's privileges

### Requirement: The cluster is bootstrapped declaratively, not by hand
The cluster's one-time setup — the `PUBLIC` revocations, the platform administrative
role, and the pooler's authentication role and lookup — SHALL be applied by an
idempotent, automated step that runs as part of deploying the environment, and SHALL be
safe to run repeatedly.

#### Scenario: A fresh environment is bootstrapped without manual steps
- **WHEN** an environment is deployed from scratch
- **THEN** the cluster is fully bootstrapped with no operator running SQL by hand

#### Scenario: Bootstrap is repeatable
- **WHEN** the bootstrap runs again against an already-bootstrapped cluster
- **THEN** it succeeds and leaves the cluster in the same state

#### Scenario: Bootstrap failure does not yield a half-configured platform
- **WHEN** the bootstrap cannot reach the cluster
- **THEN** the process that depends on it does not start serving

### Requirement: Provisioning a deployment requires no pooler restart or reconfiguration
Adding or removing a deployment SHALL NOT require restarting the pooler, and SHALL NOT
interrupt other deployments' connections.

#### Scenario: A new deployment is provisioned
- **WHEN** a database and role are created for a new deployment
- **THEN** that deployment can connect through the pooler without any pooler restart

#### Scenario: Existing deployments are undisturbed
- **WHEN** a deployment is provisioned or removed
- **THEN** other deployments' connections are not interrupted

### Requirement: The pooler runs more than one instance behind a stable endpoint
The pooler SHALL run at least two instances behind one stable in-cluster endpoint, so
that the loss of a single instance does not disconnect the whole fleet.

#### Scenario: One instance is lost
- **WHEN** one pooler instance is drained or restarted
- **THEN** new connections are served by a remaining instance

#### Scenario: Client-side limits are understood as per-instance
- **WHEN** a client connection limit is configured on the pooler
- **THEN** it applies per instance, and the platform's effective limit is that value multiplied by the instance count

### Requirement: A single global connection limit applies to all deployments
The pooler SHALL apply one connection limit shared by every deployment rather than a
per-plan limit.

#### Scenario: No per-plan differentiation
- **WHEN** deployments on different plans connect
- **THEN** the same connection limit applies to each

### Requirement: PostgreSQL and the pooler run under explicit resource bounds
Both SHALL declare CPU and memory requests and limits, and PostgreSQL's own memory
configuration SHALL be set below its container memory limit so that the container is
not terminated for exceeding it.

#### Scenario: Memory ceiling sits below the container limit
- **WHEN** PostgreSQL runs at its configured maximum memory usage
- **THEN** it remains below its container memory limit

#### Scenario: Resource bounds are declared
- **WHEN** the tenant cluster is deployed
- **THEN** PostgreSQL and each pooler instance declare CPU and memory requests and limits

### Requirement: Physical storage safety does not rely on the volume's declared size
Because the cluster's storage class enforces no size limit and cannot expand a volume,
the platform SHALL treat the tenant cluster's storage budget as self-imposed, monitor
the node's actual free disk, and alert an operator when the reserve is crossed.

#### Scenario: The reserve is crossed
- **WHEN** the node's free disk falls below the configured reserve
- **THEN** an operator is alerted

#### Scenario: No automatic global degradation
- **WHEN** the reserve is crossed
- **THEN** the platform does not automatically place unrelated deployments in read-only mode or suspend them

#### Scenario: Logical quotas are not the volume's protection
- **WHEN** the sum of all deployments' allowances exceeds the storage budget
- **THEN** the platform still operates, and physical safety rests on monitoring rather than on the quota sum

### Requirement: Tenants may install only trusted extensions
A deployment role SHALL be able to install PostgreSQL's trusted extensions in its own
database, and SHALL NOT be able to install untrusted ones.

#### Scenario: A trusted extension is installable
- **WHEN** a deployment role creates a trusted extension in its own database
- **THEN** the extension is created

#### Scenario: An untrusted extension is refused
- **WHEN** a deployment role creates an untrusted extension
- **THEN** PostgreSQL refuses the operation
