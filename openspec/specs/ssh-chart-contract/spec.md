# ssh-chart-contract Specification

## Purpose

A deployment's SSH access is served by one sidecar in the deployment's own pod, and what
that sidecar offers is decided by a single declaration in the product's chart: what the
session is rooted at. This capability is the contract between a product chart and the
library chart that renders that sidecar — what a product declares, what each declaration
renders, which pod-level facilities each requires, which runtime inputs the chart supplies,
and what a product that declares nothing gets, which is nothing at all.

## Requirements

### Requirement: A product declares a session root, or declares no SSH access
A product chart MUST declare exactly one session root to obtain SSH access, and the library
chart MUST offer exactly two values for it:

- **a volume root**, naming a path the sidecar mounts, for a product exposing data it owns;
- **an application-container root**, for a product whose pod runs code its owner wrote.

There MUST be no default and no fallback. A chart requesting a sidecar without declaring a
session root MUST fail to render, and MUST NOT be given either value by inference — in
particular, neither the presence nor the absence of a volume MUST select one.

A product declaring no session root MUST render no sidecar, no Service, and no other SSH
resource. Its deployments are consequently not routable at the SSH edge, which derives a
deployment's upstream address from a Service name that does not exist. This is the outcome
for a product with nothing to expose and no tenant code to reach, and it MUST be reached by
declaring nothing rather than by declaring a third value.

#### Scenario: A volume-rooted product renders a sidecar
- **WHEN** a product declaring a volume session root is deployed
- **THEN** its namespace contains the sidecar and its Service, and its release name is routable

#### Scenario: An application-rooted product renders a sidecar
- **WHEN** a product declaring an application-container session root is deployed
- **THEN** its namespace contains the sidecar and its Service, and its release name is routable

#### Scenario: A product declaring nothing renders nothing
- **WHEN** a product that declares no session root is deployed
- **THEN** its namespace contains no SSH resource, and a connection using its release name as
  the username reaches nothing

#### Scenario: A sidecar without a session root does not render
- **WHEN** a chart requests the sidecar and declares no session root
- **THEN** the render fails naming the missing declaration, rather than producing a sidecar

#### Scenario: A volume is not a declaration
- **WHEN** a product owning a persistent volume declares no session root
- **THEN** it renders no SSH resource, because the volume did not select one

### Requirement: No product acquires SSH access by omission
The classification of every product in the catalog MUST be asserted exhaustively: each
product chart is either volume-rooted, application-rooted, or renders no SSH resource, and
which one MUST be pinned rather than left to whatever the chart happens to render.

A product added without a classification MUST fail that assertion. The value that grants a
shell is the one an author has to write deliberately, and the safe outcome is the one
reached by writing nothing — so the assertion exists to keep the safe outcome from drifting
silently, and to make a new product's access a decision somebody made rather than one that
happened.

#### Scenario: An unclassified product fails the assertion
- **WHEN** a product chart is added and its SSH classification is not stated
- **THEN** the assertion fails rather than accepting whatever the chart renders

#### Scenario: A product changing bucket fails the assertion
- **WHEN** a product's chart begins rendering a session root other than the one pinned for it
- **THEN** the assertion fails

### Requirement: The session root decides what a session may do
A deployment's permitted operations MUST follow from its declared session root, and the
sidecar MUST be given that declaration rather than left to infer it from what the pod
exposes.

A **volume-rooted** deployment MUST serve file transfer within its session root and nothing
else: no interactive shell, no remote command execution, and no database tooling.

An **application-rooted** deployment MUST serve an interactive shell, remote commands, file
transfer, and — where the product has a database — the database tooling.

Port forwarding is governed by the forward allowlist for both, which admits nothing unless
the chart supplies one.

Inferring the answer from the pod would make a capability a consequence of unrelated
configuration: a pod that gained a shared process namespace for any other reason would
thereby grant a shell in the application container to every tenant of that product. The
declaration is what is checked, so that cannot happen.

#### Scenario: A volume-rooted session offers files only
- **WHEN** a user opens a session against a volume-rooted deployment
- **THEN** file transfer within the session root is served, and a shell, a remote command and
  the database tooling are each refused by name

#### Scenario: An application-rooted session offers everything
- **WHEN** a user opens a session against an application-rooted deployment
- **THEN** a shell, remote commands and file transfer in the application container are served

#### Scenario: Pod configuration does not grant a capability
- **WHEN** a volume-rooted deployment's pod shares a process namespace for an unrelated reason
- **THEN** its sessions still serve file transfer only

### Requirement: A volume root is mounted read-only and does not depend on the application
A volume-rooted deployment MUST mount into the sidecar only what the product exposes, with
each mount read-only, and MUST NOT mount a volume holding database or other internal state.
Where only part of a volume may be read, the chart MUST mount only that part.

Read-only MUST be a property of the mount rather than a setting inside the sidecar, so that
it holds against the session regardless of what the session is. The pod MUST NOT grant the
sidecar any capability that would let it remount what it is given.

A volume-rooted session MUST NOT depend on the application container in any way: it MUST
serve while the application is failing, restarting, crash-looping, or unable to start at
all, provided the pod exists and the sidecar is running. This is the state in which
retrieving a deployment's data matters most.

#### Scenario: Exposed data is readable
- **WHEN** a user opens a session against a volume-rooted deployment
- **THEN** the exposed data is listable and readable within the session root

#### Scenario: Internal state is not exposed
- **WHEN** a deployment also owns a volume holding database or other internal state
- **THEN** nothing corresponding to it appears in the session

#### Scenario: Only the exposed part of a volume is visible
- **WHEN** a product exposes one subdirectory of a volume whose other contents must stay unread
- **THEN** the session root contains that subdirectory's contents and nothing else from that volume

#### Scenario: Writes are refused by the kernel
- **WHEN** a session attempts to create, modify or delete anything within a volume session root
- **THEN** the operation fails, and it fails because the mount is read-only rather than because
  the sidecar declined it

#### Scenario: Files are readable regardless of their ownership
- **WHEN** the exposed data is owned by a user and mode the application chose
- **THEN** the session reads it without the chart being told which user that is

#### Scenario: Data is reachable while the application is broken
- **WHEN** the application container is crash-looping or cannot start
- **THEN** a session still lists and reads the exposed data

### Requirement: An application root requires a shared process namespace and nothing more
A pod running an application-rooted deployment MUST share its process namespace across
containers. It MUST NOT run any container privileged, MUST NOT share the node's process
namespace, and MUST NOT request any non-default capability. The application container MUST
NOT be granted anything by this contract.

Sharing the pod's process namespace is what lets the sidecar reach the application's
filesystem and environment. It confers nothing outside the pod, because process identifiers
resolve within the namespace that shares them.

**Attaching a debugger or profiler is deliberately not offered.** `strace`, `gdb` and
`py-spy` need `CAP_SYS_PTRACE`, and tenant namespaces enforce Pod Security `baseline`, which
refuses every non-default capability at admission — a pod requesting one never schedules.
Granting it requires raising the namespace's enforcement level, which is a change to what
the platform guarantees about tenant pods and is decided separately.

Where the pod does not share a process namespace, a session that depends on reaching the
application container MUST report that plainly rather than failing obscurely.

#### Scenario: The sidecar sees the application's processes
- **WHEN** the sidecar enumerates processes
- **THEN** the application container's processes are visible to it

#### Scenario: The blast radius is the pod
- **WHEN** the sidecar attempts to reach a process outside its own pod
- **THEN** it cannot address one

#### Scenario: The pod is admitted under the tenant namespace's policy
- **WHEN** an application-rooted deployment is applied to a tenant namespace
- **THEN** its pod is admitted and schedules, rather than being refused for requesting a
  non-default capability

#### Scenario: No privileged container and no added capability
- **WHEN** the pod specification is inspected
- **THEN** no container is privileged and no container requests a non-default capability

#### Scenario: A missing shared process namespace is reported
- **WHEN** an application-rooted deployment's pod does not share a process namespace
- **THEN** a session that needs the application container says so, naming the likely cause

### Requirement: The chart runs the platform's sidecar image at a pinned version
Every deployment with SSH access MUST run the platform's own sidecar image, referenced by an
exact version tag supplied as a system value that a tenant cannot set. It MUST NOT reference
the image by a moving tag, and no product MUST run a different SSH server.

A tenant-settable reference here would let a tenant substitute the container that holds the
platform's trusted key and enters their application. A moving tag would make the version a
pod runs a function of when it last restarted and what its node had cached.

#### Scenario: Image is pinned and platform-supplied
- **WHEN** any deployment with SSH access is rendered
- **THEN** the sidecar's image is an exact version tag taken from a system value

#### Scenario: A tenant cannot choose the sidecar image
- **WHEN** a tenant supplies a value attempting to change the sidecar image
- **THEN** the rendered sidecar image is unaffected

#### Scenario: One server across the fleet
- **WHEN** any product's rendered pod is inspected
- **THEN** it contains at most one SSH server container, and that container is the platform's image

### Requirement: The chart supplies every runtime input the sidecar requires
The chart MUST supply the sidecar with all of the inputs its image declares as required: the
platform's trusted public key, the declared session root, both spellings of the release
identity, and the account the edge authenticates as. The sidecar exits rather than starting
when any is missing, so an omission is a pod that will not run rather than one that runs
wrongly.

Both spellings of the release identity MUST be read from platform-projected values
directly, and neither MUST be taken from a pod label. A label carrying either would be the
same fact by a longer route, and it would make the pod template's hash change on every
apply — so a redeploy with identical values would cycle the deployment's pod rather than
being a no-op, which is a cost no product should pay merely for having SSH access. One
value, read once in one render, is also what makes the two spellings unable to disagree.

A product MAY render a release label for its own reasons — a log pipeline keyed on it, say
— and that is independent of this contract.

Where the product has a database and the deployment is application-rooted, the chart MUST
additionally supply the forward allowlist and the connection details, and MUST supply the
connection details as a complete set. A partial set MUST abort startup: it means the
projection that should have supplied them is broken, and a sidecar that started anyway would
surface that as a connection error at the moment someone needed the database and furthest
from its cause.

Every one of these MUST come from values the platform projects, never from values a tenant
supplies. The connection details MUST reach the sidecar's own environment, so that database
access does not depend on the application container being alive — which is the state a
developer is most likely connecting to investigate.

#### Scenario: A rendered deployment starts
- **WHEN** a deployment with SSH access is rendered and applied
- **THEN** the sidecar starts and serves, rather than exiting on a missing input

#### Scenario: The release identity is the deployment's own
- **WHEN** a session reports the release it landed on
- **THEN** the reported identity is that pod's release, not a value derived from the pod's name

#### Scenario: Neither spelling is read from a pod label
- **WHEN** a rendered sidecar's release inputs are inspected
- **THEN** both are projected from platform values, and neither depends on a label

#### Scenario: SSH access does not make a redeploy cycle the pod
- **WHEN** a deployment with SSH access is rendered twice with identical values and a
  different release identity each time
- **THEN** its pod template is unchanged, so a redeploy with identical values remains a no-op

#### Scenario: Tenant values cannot supply these inputs
- **WHEN** a tenant sets values attempting to change the trusted key, the session root, the
  forward allowlist, or the database details given to the sidecar
- **THEN** the rendered sidecar is unaffected

#### Scenario: Database tooling works with the application stopped
- **WHEN** the application container is not running and a developer runs the database client
  through the sidecar
- **THEN** it connects to the deployment's database

### Requirement: The forward allowlist admits the deployment's database and nothing else by default
The forward allowlist the chart supplies MUST name the deployment's own database endpoint,
spelled exactly as a client will address it, and MUST NOT admit arbitrary destinations.

Tenant egress reaches the public internet on every port, so an unconstrained forwarder would
be an authenticated open relay originating from the platform's address. The allowlist is the
constraint that prevents it, and it is only effective if the spelling the chart renders and
the spelling a client uses are identical.

A deployment with no forwardable endpoint MUST refuse every forward. An empty allowlist MUST
be expressed as an explicit refusal and MUST NOT be expressed by omitting the constraint,
because the server's own default is to permit forwarding to any destination — so silence
would turn "nothing to allow" into "allow everything".

#### Scenario: The database is forwardable
- **WHEN** a developer forwards a local port to the deployment's database endpoint as the chart
  spells it
- **THEN** the forward carries traffic

#### Scenario: Other destinations are refused
- **WHEN** a developer forwards to any destination the allowlist does not name
- **THEN** the forward is refused

#### Scenario: The spelling is the one clients use
- **WHEN** the platform documents the address a client should forward to
- **THEN** it is byte-identical to what the chart renders into the allowlist

#### Scenario: A deployment with nothing to forward to refuses every forward
- **WHEN** a developer forwards to any destination through a deployment whose chart supplies no
  allowlist
- **THEN** the forward is refused

### Requirement: Every deployment presents the same Service to the edge
Whatever its session root, a deployment MUST expose its sidecar through a ClusterIP Service
following the platform's single naming convention and listening on the platform's single
sidecar port, rendered as part of the Helm release so it is created, upgraded and deleted
with the deployment. The chart MUST NOT render any routing object: the edge resolves where a
username goes at connection time, so nothing in the release describes the route.

The naming convention is shared with the SSH edge, which derives a deployment's upstream
address from it, and MUST NOT be changed on one side alone: a chart rendering a name the edge
does not expect produces a deployment that authenticates and then reaches nothing.

The Service MUST publish not-ready addresses, so its endpoints include the deployment's pod
whenever that pod exists, irrespective of the pod's readiness. This Service does not front the
application: it fronts an administrative sidecar whose availability is deliberately
independent of the application's.

#### Scenario: Service is rendered by the chart
- **WHEN** the Helm release is installed
- **THEN** a ClusterIP Service targeting the sidecar on the platform's sidecar port exists in
  the deployment's namespace

#### Scenario: Service name matches what the edge derives
- **WHEN** the edge derives a deployment's upstream address
- **THEN** it names the Service the chart rendered for that deployment

#### Scenario: The edge needs no knowledge of the session root
- **WHEN** the edge resolves a deployment's upstream address
- **THEN** it requires no knowledge of what that deployment's sessions are rooted at

#### Scenario: Chart renders no routing object
- **WHEN** the chart's output is rendered
- **THEN** it contains no object describing an SSH route

#### Scenario: Service endpoints include a not-ready pod
- **WHEN** the deployment's pod exists but is not ready
- **THEN** the Service's endpoints still include that pod's address

#### Scenario: Uninstall removes everything the deployment contributed
- **WHEN** the Helm release is uninstalled
- **THEN** the Service and sidecar are removed with it, and the username stops being routable

### Requirement: The sidecar is liveness-probed independently of the application
The sidecar MUST declare a liveness probe against its SSH port, so a sidecar whose server has
stopped serving is restarted rather than left in place. Because application readiness does not
gate routing to the Service, the sidecar's own liveness is the only mechanism preventing
connections being routed to a sidecar that cannot serve them.

The probe MUST test the SSH port's acceptance of connections and MUST NOT depend on the
application container, on any mounted volume, or on any credential.

#### Scenario: Sidecar stops serving
- **WHEN** the sidecar's SSH server is no longer accepting connections on its port
- **THEN** the liveness probe fails and the sidecar container is restarted

#### Scenario: Probe is independent of the application
- **WHEN** the application container is unhealthy but the sidecar is accepting connections
- **THEN** the sidecar's liveness probe succeeds and the sidecar is not restarted

#### Scenario: Probe does not authenticate
- **WHEN** the liveness probe runs
- **THEN** it establishes no session and uses no deployment credential

### Requirement: The tenant's namespace holds no credential for this feature
The chart MUST NOT render a password, a private key, or any registered user's public key into
the deployment's namespace. The only key material a deployment holds for SSH access is the
platform's public key, which the sidecar trusts, and the host key the sidecar generates for
itself at startup.

The keys that authenticate a person are resolved at the edge and never reach a tenant. The
account the edge authenticates to the sidecar as MUST be the Helm release name, and no product
MUST be able to choose a different one: the edge derives it from the deployment's own record
and reads no cluster object, so a chart free to name it otherwise would produce a deployment
the edge cannot log in to.

That account is not the username a person types. Which deployment a connection opens is
decided at the edge from an identifier the tenant's namespace does not hold and MUST NOT need
to hold; the chart's obligation ends at rendering the account the edge will present. A change
to the identifier clients present therefore MUST NOT require any chart to be re-rendered.

#### Scenario: No password exists
- **WHEN** the chart is rendered or installed
- **THEN** no password is generated or stored, and password authentication is unavailable

#### Scenario: No user keys reach the tenant namespace
- **WHEN** a deployment's namespace is inspected
- **THEN** it contains no registered user's public key and no private key

#### Scenario: The login account is the release name
- **WHEN** any product's chart is rendered
- **THEN** the account the edge authenticates as is the Helm release name, and no product
  overrides it

#### Scenario: The client-facing identifier appears nowhere in the release
- **WHEN** a deployment's rendered release is inspected
- **THEN** nothing in it records the username a client presents to reach this deployment
