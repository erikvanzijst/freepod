# ssh-sidecar-image Specification

## Purpose

The `dev` access profile needs an SSH server that can forward a TCP connection to the
database pooler, host a shell into the application container beside it, and run the
platform's PostgreSQL tooling at the server's own version. This capability defines that
image: what it contains, how its SSH server is configured, what configuration it takes at
startup, and what it refuses to run without. The image is a self-contained artifact; the
pod-level settings it depends on, and the chart that supplies its configuration, are
defined elsewhere.

## Requirements

### Requirement: The image is platform-owned, versioned, and never re-pushed
The image MUST be built from a build context in this repository, pinned to explicit base and package versions so a rebuild of a given tag produces a functionally identical image, and published under an immutable version tag.

An already-published tag MUST NOT be overwritten. A change to the image is a new version, and consumers are repointed at it. The publishing path MUST enforce this rather than only documenting it: an attempt to push a version the registry already holds MUST fail.

The image MUST NOT contain any credential, key, or tenant data. Everything it needs to authenticate a session arrives at runtime.

#### Scenario: Rebuild is reproducible
- **WHEN** the image is rebuilt from the same source at the same version
- **THEN** it provides the same SSH server behavior, dispatcher behavior, and tool versions

#### Scenario: Re-pushing a published version is refused
- **WHEN** a publish is attempted for a version tag the registry already holds
- **THEN** it fails without overwriting the published image

#### Scenario: No baked secrets
- **WHEN** the published image is inspected
- **THEN** it contains no private key, no authorized key, no password, and no tenant data

### Requirement: The image carries its own version, and consumers pin it exactly
The image's version MUST be declared in its build context, and that declaration MUST be the single input from which the publishing path derives the tag it pushes. A version is therefore a reviewable edit in this repository, not an argument someone types at a terminal.

That version MUST be independent of the version of any chart that consumes the image. The two move on their own cadences: a chart changes for reasons that do not touch the image, and the coupling runs one way — the image reference lives in the chart, so a new image cannot reach a deployment except through a chart change.

A consumer MUST reference the image by an exact version tag and MUST NOT reference it by a moving tag. A moving tag makes the version a pod runs a function of when that pod last restarted and what its node had cached, which is not a property any deployment should have.

#### Scenario: Published tag comes from the declared version
- **WHEN** the image is published
- **THEN** the tag it carries is the version declared in its build context

#### Scenario: Chart version and image version are not required to agree
- **WHEN** a consuming chart is changed without any change to the image
- **THEN** the chart takes a new version and continues to reference the existing image version

#### Scenario: Consumers pin an exact version
- **WHEN** a consumer references the image
- **THEN** it names an exact version tag rather than a moving one

### Requirement: The SSH server accepts public keys only
The SSH server MUST authenticate by public key alone. Password authentication, keyboard-interactive authentication, and any other interactive fallback MUST be disabled, and root login by password MUST be refused.

The set of trusted keys MUST be supplied at runtime and MUST NOT be baked into the image. The image trusts exactly the key material it is given — in normal operation the single public key of the platform's SSH edge — and no other.

#### Scenario: Password authentication is refused
- **WHEN** a client attempts password authentication against the server
- **THEN** the attempt is refused and no password prompt succeeds

#### Scenario: Only the supplied key authenticates
- **WHEN** a client presents a public key that was not supplied to the container at startup
- **THEN** authentication fails

#### Scenario: The supplied key authenticates
- **WHEN** a client presents the public key supplied to the container at startup
- **THEN** authentication succeeds

### Requirement: The server refuses to start without a trusted key
If no trusted public key is supplied at startup, the container MUST fail to start and MUST say why. It MUST NOT start an SSH server that no one can authenticate to, because that failure is indistinguishable from a network problem and would be diagnosed as one.

#### Scenario: Missing key material
- **WHEN** the container is started with no trusted public key
- **THEN** it exits with a non-zero status and an error naming the missing configuration

#### Scenario: Unusable key material
- **WHEN** the container is started with key material that is not a valid SSH public key
- **THEN** it exits with a non-zero status rather than starting with an empty trust set

### Requirement: The session root is declared, and the image serves nothing outside it
The image MUST take the session root as a declared input naming one of two things: a path the container has mounted, or the filesystem of the application container sharing the pod. It MUST confine every session to that root, and MUST NOT serve any path outside it.

A confined session runs a program, and that program's own prerequisites MUST be reachable inside the confinement. Where the declared root cannot supply them — a mounted path holds the product's data and nothing else — the image MUST supply them itself, and a session MUST then begin at the declared path rather than wherever those prerequisites live. What the image supplies MUST hold nothing of the tenant's and nothing of the platform's: it exists so that a transfer can run, and carries no credential, no configuration and no data.

The image MUST decide what a session may do from this declaration alone, never by testing what the pod happens to expose. A capability that is granted because a facility was found is a capability that appears when unrelated configuration changes.

A declared application-container root that cannot be resolved — because the pod does not share a process namespace, or no application process is identifiable — MUST be reported as such and MUST NOT fall back to serving the container's own filesystem. The sidecar's filesystem holds none of the user's data and is not a lesser version of what was asked for.

#### Scenario: A path outside the session root is unreachable
- **WHEN** a session requests a path outside its session root by any spelling, including one that traverses upward
- **THEN** the request is refused and no path outside the root is read or written

#### Scenario: The declaration decides, not the pod
- **WHEN** a container declaring a mounted-path session root runs in a pod that shares a process namespace
- **THEN** its sessions are still rooted at the mounted path

#### Scenario: A session begins at the declared path
- **WHEN** a session opens against a deployment whose declared root is a mounted path
- **THEN** it starts at that path, and the paths it reports for the product's data are the ones the product documents

#### Scenario: What the image supplies to run a transfer holds nothing of anyone's
- **WHEN** a session inspects everything reachable outside the declared path
- **THEN** it finds only what the transfer program itself requires, and no credential, configuration or data of the tenant's or the platform's

#### Scenario: An unresolvable application root is reported
- **WHEN** a container declaring an application-container root cannot identify the application process
- **THEN** the session reports that, naming the likely cause, and no session is served from the sidecar's own filesystem

### Requirement: File transfer is served by the image's own tooling
The image MUST serve file transfer from tooling it carries itself, chrooted into the session root. It MUST NOT look for a file-transfer helper in the application container's filesystem, and MUST NOT make file transfer conditional on what a tenant's image contains.

A tenant's image is theirs and commonly contains no such helper — the image the platform's own build pipeline produces does not. Serving from the sidecar makes file transfer a property of the platform rather than of what a user happened to install, and gives one code path exercised by every session on every deployment rather than a fallback that is rarely taken and therefore rarely known to work.

#### Scenario: Transfer works against a minimal image
- **WHEN** a client copies a file to or from a deployment whose application image contains no file-transfer tooling
- **THEN** the transfer succeeds

#### Scenario: Transfer lands in the session root
- **WHEN** a client uploads a file to an application-rooted deployment
- **THEN** it appears in the application container's own filesystem, not in the sidecar's

A transfer into an application container runs as the application's user, and the transfer program resolves the user it runs as before it does anything else. That user MUST therefore be named in the application image's user database, and a transfer where it is not MUST be refused with a reason naming the uid. This is the one thing the image asks of a tenant's image for a transfer, and it is what `USER` in a Dockerfile ordinarily provides.

#### Scenario: The tenant's image is not consulted
- **WHEN** a session requests file transfer
- **THEN** the server uses its own tooling regardless of what the application image contains

#### Scenario: A transfer as a user the image does not name is refused
- **WHEN** a transfer is requested into an application that runs as a uid its image's user database does not name
- **THEN** it is refused, and the reason names the uid

### Requirement: Whether a session may write follows from the filesystem
Whether a session may modify what it can reach MUST be taken from the filesystem of the declared path rather than from a separate setting. A declared path that is mounted read-only MUST be served read-only.

It MUST be taken from the declared path specifically, and not from whatever the confinement happens to be rooted at: where the image supplies a session's prerequisites itself, those live in the container's own writable layer, and reading the answer from there would report a read-only mount as writable.

Two independent statements of the same intent can disagree, and the one that would be wrong is the one inside the container. The kernel already knows the answer, refuses a write regardless of the user the session runs as, and cannot be overridden by a container holding no capability to remount.

#### Scenario: A read-only root is served read-only
- **WHEN** a session's root is a read-only mount
- **THEN** the server declines write operations, and a write attempted anyway is refused by the filesystem

#### Scenario: A writable root is writable
- **WHEN** a session's root is a writable filesystem
- **THEN** the session may create and modify files within it

#### Scenario: Ownership does not decide readability
- **WHEN** the session root holds files owned by another user with restrictive modes
- **THEN** the session reads them, without the container being told which user owns them

### Requirement: The server itself does not chroot, and forwarding is unaffected by confinement
The SSH server MUST NOT be configured to chroot connections before a session starts. A connection that opens no session — a port forward — MUST NOT be confined at all: the process that opens a forwarded connection would otherwise run inside a filesystem with no resolver configuration, and name resolution for the forward's target would fail.

Confinement to the session root is applied to a session once it has started, and therefore reaches only sessions. This is what lets one server both confine file transfer to a session root and forward to a named destination.

#### Scenario: Forwarding resolves its target
- **WHEN** a client opens a forwarded connection to a target addressed by hostname
- **THEN** the server resolves that hostname and connects, rather than failing to resolve it

#### Scenario: A confined session does not confine a forward
- **WHEN** a client opens a forward and a session on one connection
- **THEN** the session is confined to the session root and the forward reaches its destination

### Requirement: Forwarding is local-only and constrained to an allowlist
The server MUST permit local port forwarding and MUST refuse remote port forwarding. Permitted forward destinations MUST be an explicit allowlist supplied at runtime; a forward to any other destination MUST be refused.

Agent forwarding, X11 forwarding, and gateway ports MUST be disabled.

An allowlist is required rather than recommended because the pod's egress reaches the public internet on every port: an unconstrained forwarder would be an authenticated open TCP relay originating from the platform's address.

The allowlist itself is optional, because a deployment may have nothing to forward to. A container supplied with none MUST refuse every forward, and MUST express that refusal explicitly in the server's configuration rather than by omitting the constraint: the server's own default is to permit forwarding to any destination, so an omitted constraint would turn "nothing to allow" into "allow everything".

#### Scenario: Permitted destination is forwarded
- **WHEN** a client forwards to a destination in the supplied allowlist
- **THEN** the connection is established and carries traffic

#### Scenario: Other destinations are refused
- **WHEN** a client forwards to a destination absent from the allowlist
- **THEN** the server refuses the channel

#### Scenario: Remote forwarding is refused
- **WHEN** a client requests a remote forward
- **THEN** the request is refused

#### Scenario: Agent forwarding is unavailable
- **WHEN** a client requests agent forwarding
- **THEN** the request is refused

### Requirement: Forward destinations are matched as the client writes them
A permitted destination MUST be matched against the destination string as the client requested it, and the allowlist MUST therefore be expressed in the same form a client will use. The image MUST document this, because a mismatch between the allowlist's spelling of a host and the client's produces a refusal that reads like an authorization failure.

#### Scenario: Equivalent spellings are not interchangeable
- **WHEN** the allowlist names a destination in one form and a client requests an equivalent but differently spelled form
- **THEN** the behavior is documented, so an operator configuring the allowlist knows the two must agree

### Requirement: The image carries PostgreSQL client tooling matching the tenant cluster
The image MUST include the PostgreSQL command-line client and dump/restore tools at a major version no older than the tenant database cluster's, so that dumps taken through this sidecar are never rejected for a version mismatch.

Running these tools server-side is the point: a developer's local `pg_dump` older than the server aborts, and that failure is not fixable from the client.

#### Scenario: Dump tooling is not older than the server
- **WHEN** the image's dump tool version is compared against the tenant cluster's server version
- **THEN** the tool's major version is greater than or equal to the server's

#### Scenario: Tools are present and runnable
- **WHEN** the client and dump tools are invoked inside the image
- **THEN** each reports its version and exits successfully

### Requirement: Database tooling takes its connection details from the environment
The PostgreSQL tools MUST connect using the deployment's database connection details as supplied in the container's own environment, so that invoking the client with no arguments opens a session against that deployment's database.

The sidecar MUST NOT depend on the application container being alive to learn these details. A developer connects precisely when the application is broken, and connection details read from a process that is crash-looping would be unavailable exactly then.

The connection details are optional **as a set**. The toolbox is a facility this image offers, not a precondition it imposes: a container supplied with none MUST start and MUST serve every other session path, and requests for the database tools MUST be declined with a message naming the absence of a database rather than run and left to fail as a client connection error.

A container supplied with an *incomplete* set MUST exit at startup, naming what was supplied and what is missing. Nothing supplied means a deployment without a database; something supplied means the projection that should have supplied the rest is broken, and a container that started anyway would surface that inside the client at the moment someone needed the database and furthest from its cause.

#### Scenario: Client with no arguments connects to the deployment's database
- **WHEN** the PostgreSQL client is invoked with no arguments in a container supplied with the deployment's connection details
- **THEN** it attempts a connection to that database rather than to a default or a local socket

#### Scenario: Availability does not depend on the application container
- **WHEN** the application container is not running
- **THEN** the sidecar still has the connection details it needs

#### Scenario: A container with no database serves every other session path
- **WHEN** a container is supplied with none of the connection details
- **THEN** it starts and serves sessions, and only the database tooling is unavailable

#### Scenario: Database tools are declined rather than left to fail
- **WHEN** a client requests a database tool on a container supplied with no connection details
- **THEN** the request is refused with a message naming the absence of a database

#### Scenario: An incomplete set of connection details fails fast
- **WHEN** a container is supplied with some but not all of the connection details
- **THEN** it exits with a non-zero status naming what is missing, rather than starting

### Requirement: Host keys are generated at startup and are not persisted
The server MUST generate its host key at container start. Host keys MUST NOT be baked into the image, because every deployment would then share one, and MUST NOT be required to persist across restarts.

Only a modern elliptic-curve host key is required. Generating large RSA host keys on every start delays the port opening for seconds with no benefit here, since the client-facing host identity is the edge's and the connection from the edge to this server does not pin the sidecar's key.

#### Scenario: Each container has its own host key
- **WHEN** two containers are started from the same image
- **THEN** they present different host keys

#### Scenario: The port opens promptly
- **WHEN** the container starts
- **THEN** the SSH port begins accepting connections without waiting on large-key generation

### Requirement: The server listens on the platform's sidecar port
The server MUST listen on the platform's conventional sidecar SSH port rather than the default SSH port, matching the port the platform's tenant network policy admits from the SSH edge.

#### Scenario: Server is reachable on the sidecar port
- **WHEN** a client connects to the container on the platform's sidecar port
- **THEN** an SSH handshake completes

### Requirement: Configuration is supplied at runtime and validated before the server starts
Everything that varies per deployment — the trusted public key, the session root, the permitted forward destinations, the release identity, and the deployment's database connection details — MUST be supplied to the container at startup rather than built in.

Supplied configuration MUST be validated before the SSH server starts, and a container given invalid configuration MUST fail loudly rather than start in a degraded state. The contract MUST be documented, since it is the interface a chart will target.

The release identity MUST be taken as **two** inputs, both required: the number a user sees, which the session banner reports, and the platform's own identifier for the release, which the image records where it can be read beside the logs that identifier keys. Neither substitutes for the other, and a container given only one MUST refuse to start: with only the identifier the banner would name the release in a spelling no user can look up, and with only the number nothing the pod writes could be correlated with the release it belongs to.

Not every input is required. Those describing the server itself — the trusted key, the session root, both spellings of the release identity, the login account — are; those describing a facility a deployment may not have — the forward allowlist, the database connection details — are not. The documentation MUST say which are which, because the difference is what decides whether an absent value is a pod that will not start or a deployment that simply has no database.

#### Scenario: Configuration contract is documented
- **WHEN** an operator or a chart author needs to run the image
- **THEN** the repository documents every input the image accepts, which are required, and what each does

#### Scenario: Invalid configuration fails fast
- **WHEN** the container is given a malformed forward allowlist
- **THEN** it exits with a non-zero status and an error identifying the input, rather than starting with forwarding misconfigured

#### Scenario: Half a release identity is not a release identity
- **WHEN** the container is given either spelling of the release identity but not the other
- **THEN** it exits with a non-zero status and an error naming the missing one

#### Scenario: No session root is not a default
- **WHEN** the container is given no session root
- **THEN** it exits with a non-zero status naming the missing input, rather than choosing one

### Requirement: The image runs as root and holds no capability beyond its purpose
The SSH server runs as root because the dispatcher must read another container's process filesystem and enter it. The image MUST NOT require additional privilege beyond what the pod grants it, MUST NOT assume it can mount filesystems, and MUST NOT require a privileged container.

The image MUST behave correctly, and report clearly, when the pod-level facilities it can use are absent rather than assuming they are present.

#### Scenario: No privileged mode required
- **WHEN** the image runs without privileged mode and without mount capability
- **THEN** the SSH server starts and serves normally

#### Scenario: Absent pod facilities are reported, not assumed
- **WHEN** the image runs in a pod that does not share a process namespace with an application container
- **THEN** it starts and serves, and reports the limitation when a session depends on that facility
