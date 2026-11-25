## Purpose

Caelus deployments run as isolated Helm releases, and users need a way to browse and download their deployment's files. This capability provides the shared, platform-owned SSH edge that terminates inbound SFTP connections and routes them to the correct per-deployment sidecar. A single SSH reverse proxy (sshpiperd) per environment exposes one public port and, for each connection, obtains both the route and the authentication decision from the SSH auth resolver rather than from any cluster object. The client authenticates with a public key registered on the account owning the deployment its username names; the edge authenticates to the sidecar with a platform-held key. No password exists anywhere on the path. Environments stay separated at the network layer, routing follows deployments as they come and go with nothing to create or remove, and a stable proxy host key keeps clients' `known_hosts` entries valid across proxy redeploys.

## Requirements

### Requirement: One public SSH entry point per environment with configurable ports
Each environment (prod, dev) MUST expose a single SSH endpoint for its deployments, terminating at that environment's SSH reverse proxy (sshpiperd) running in a platform namespace. The environments share one public IPv4 address and SSH has no hostname indication, so distinct ports are the only environment discriminator. The user-facing endpoints are `freepod.eu:22` (prod) and `dev.freepod.eu:23` (dev); the home router translates these to the internal chain, where every hop MUST avoid port 22 because the cluster nodes retain their system OpenSSH there: router :22 → floating address :2222 (prod), and router :23 → floating address :2223 (dev). The floating address is held by one of the cluster nodes. The cluster-side ports MUST be Terraform variables per environment workspace, defaulting to 2222 (prod) and 2223 (dev). The edge path MUST be plain TCP passthrough; no TLS or HTTP layer is involved. The per-environment proxy MUST be provisioned declaratively via Terraform in `tf/app/` (workspace-scoped), together with the resolver it consults.

No custom resource definition is required for routing, and none MUST be installed for this purpose: the proxy obtains routing and authentication decisions from the resolver rather than from cluster objects.

#### Scenario: Client connects to the prod endpoint
- **WHEN** an SFTP client connects to `freepod.eu` on port 22
- **THEN** the connection traverses router :22 → floating address :2222 unmodified
- **AND** the client completes an SSH handshake with the prod sshpiperd

#### Scenario: Client connects to the dev endpoint
- **WHEN** an SFTP client connects to `dev.freepod.eu` on port 23
- **THEN** the connection traverses router :23 → floating address :2223 unmodified
- **AND** the client completes an SSH handshake with the dev sshpiperd

#### Scenario: Host system SSH is unaffected
- **WHEN** an administrator connects to a cluster node on its local port 22
- **THEN** they reach the host's system OpenSSH, not sshpiperd

#### Scenario: Operator changes an environment's cluster-side port
- **WHEN** an operator changes the SSH port variable for a workspace and applies Terraform (plus the matching router forward)
- **THEN** the environment's SSH endpoint is reachable end-to-end without changes to charts or to the other environment

#### Scenario: No routing CRD is installed
- **WHEN** the cluster's custom resource definitions are inspected
- **THEN** none exists for SSH routing, and the proxy's permissions include no access to such a resource

### Requirement: Connections are routed to deployments by SSH username
The proxy MUST route each incoming SSH connection to a per-deployment upstream selected by the SSH username, obtaining that upstream from the resolver at connection time. A username that the resolver does not admit MUST be rejected during authentication without revealing whether the username exists.

Routing MUST NOT be expressed as cluster objects. The proxy MUST NOT watch, read, or require any custom resource to decide where a connection goes, so that no routing record exists to be created, removed, or left behind.

#### Scenario: Known username routes to its deployment
- **WHEN** a client authenticates with a username the resolver admits
- **THEN** the connection is proxied to the upstream the resolver returned for it

#### Scenario: Unknown username is rejected
- **WHEN** a client attempts to authenticate with a username the resolver does not admit
- **THEN** authentication fails with a generic authentication error

#### Scenario: No routing objects exist
- **WHEN** any namespace is inspected
- **THEN** it contains no object describing an SSH route

### Requirement: Routes update live without restarts or session disruption
Creating or deleting a deployment MUST take effect without restarting sshpiperd and MUST NOT disturb established SSH sessions on other routes. Deploying or deleting an application MUST NOT require any change to the proxy deployment itself, nor the creation or removal of any object dedicated to routing it.

#### Scenario: New deployment becomes reachable
- **WHEN** a new deployment is created while other users have active SFTP sessions
- **THEN** its username becomes routable without a proxy restart
- **AND** all established sessions continue uninterrupted

#### Scenario: Deleted deployment stops being routable
- **WHEN** a deployment is deleted
- **THEN** subsequent connection attempts with that username are rejected, without any routing object having been removed

### Requirement: Environment separation
A connection accepted by one environment's proxy MUST NOT reach the SFTP endpoint of a deployment belonging to the other environment. Enforcement MUST NOT depend on the routing layer alone: each environment's tenant NetworkPolicy admits only that environment's proxy pods, and that network-layer enforcement remains the guarantee.

Each environment's proxy MUST consult only its own environment's resolver, which answers only from that environment's records. A username belonging to the other environment's deployment therefore does not resolve, so the routing layer no longer offers a path to the wrong environment for the network layer to have to deny.

#### Scenario: Cross-environment access is denied
- **WHEN** a client connects to the dev SSH port using a prod deployment's username
- **THEN** the username does not resolve, and separately the connection to the prod deployment's sidecar would be denied at the network layer

#### Scenario: Network-layer enforcement is intact
- **WHEN** each environment's tenant NetworkPolicy is inspected
- **THEN** it admits only that environment's proxy pods

### Requirement: Stable proxy host key
The proxy MUST present a host key sourced from a Kubernetes Secret that persists across pod restarts, upgrades, and redeploys, so that clients' `known_hosts` entries remain valid. Upstream (sidecar) host keys MUST NOT be presented to clients and MAY change freely.

#### Scenario: Host key survives a proxy redeploy
- **WHEN** the sshpiperd Deployment is deleted and re-created by Terraform
- **THEN** clients connecting afterwards observe the same host key as before

### Requirement: The client authenticates to the edge with a registered public key
The proxy MUST authenticate the client by public key, admitting exactly the keys registered on the account that owns the deployment the username names. A client presenting a key that is not registered on that account MUST be refused.

The proxy MUST NOT hold, cache, or be configured with the set of acceptable keys. It MUST obtain the decision from the resolver for each connection, so that a key registered or revoked between two connections is honored on the second without any intervening action.

#### Scenario: Registered key is accepted
- **WHEN** a client connects with a username naming a deployment, presenting a key registered on that deployment's owning account
- **THEN** authentication succeeds and the session is established

#### Scenario: Unregistered key is refused
- **WHEN** a client presents a key that is not registered on the owning account
- **THEN** authentication is refused

#### Scenario: Revocation takes effect on the next connection
- **WHEN** a key is removed from an account
- **THEN** the next connection presenting that key is refused, with no other action taken

### Requirement: The edge authenticates to the sidecar with a platform-held key
The proxy MUST authenticate to the upstream sidecar using a key held by the platform and supplied by the resolver, never using anything the client supplied. The client's own credential MUST NOT be replayed upstream.

A tenant namespace MUST NOT hold any material that authenticates the platform to a sidecar. It holds only the public half its sidecar trusts.

#### Scenario: Upstream authentication uses the platform's key
- **WHEN** the proxy establishes the upstream connection
- **THEN** it authenticates with the platform's own key

#### Scenario: The sidecar trusts only the platform's public key
- **WHEN** a deployment's sidecar configuration is inspected
- **THEN** the only key it trusts is the platform's public key, and no user key appears there

#### Scenario: Client credentials are not forwarded
- **WHEN** a client authenticates to the proxy
- **THEN** the credential it presented is not used against the upstream
