# cli-ssh-access Specification

## Purpose

A developer with a `custom` deployment can already reach it over SSH, if they know four
things the platform knows and they do not: the edge's address, that their username is the
deployment's id, which of their keys is registered, and the exact spelling of their
database's in-cluster address. This capability is the client that supplies all four — a
shell in the application container, a forwarded database port, a server-side database
session, and a file copy — and, because the edge deliberately refuses without saying why,
the diagnosis a user gets when one of them fails.

## Requirements

### Requirement: Four commands over the deployment the project names
The client MUST provide a command opening a session in the deployment's application container, a command forwarding a local port to the deployment's database, a command opening an interactive database session, and a command copying files and directories between the local machine and the deployment's application container.

Each MUST resolve which deployment it acts on the same way every other project-scoped command does, and MUST fail with the same guidance when run outside a project or against a deployment that does not exist.

#### Scenario: Shell reaches the application container
- **WHEN** a user runs the shell command in a project whose deployment is running
- **THEN** they are placed in an interactive session in that deployment's application container

#### Scenario: Copy reaches the application container
- **WHEN** a user runs the copy command in a project whose deployment is running
- **THEN** the file is read from or written to that deployment's application container, not the sidecar

### Requirement: The shell command runs a given command instead of opening a session
The shell command MUST accept a command to run in the application container, and MUST then run it there and exit rather than opening an interactive session. The exit code MUST be the remote command's own.

The platform already serves this path — the session dispatcher routes a requested command into the application container — so a client that only opened sessions was the narrower half of a facility that exists. Words are passed to `ssh` as given and joined by it, so the container's own shell does the interpreting and a quoted pipeline stays whole, which is the behavior anyone reaching for this already knows from `ssh`.

Words after the command MUST be passed through as the remote command's, never parsed as the client's own options, because a command's flags are not the client's to claim.

A terminal MUST NOT be allocated for a given command unless the user asks for one, and MUST be allocated for an interactive session. A pty rewrites what passes through it — line endings translated, standard error folded into standard output — so allocating one for a command whose output is redirected or piped corrupts it; a full-screen program needs one, which is why asking MUST remain possible.

#### Scenario: A command runs in the application container
- **WHEN** a user runs the shell command with a command in a project whose deployment is running
- **THEN** the command runs in the application container and the client exits with the command's own exit code

#### Scenario: The command's own options are not the client's
- **WHEN** the given command carries flags the client also defines
- **THEN** they reach the remote command unparsed

#### Scenario: Output that is redirected is not rewritten
- **WHEN** a user redirects the output of a command run this way
- **THEN** no terminal was allocated for it, and the bytes are the command's own

#### Scenario: A full-screen program is given a terminal
- **WHEN** a user asks for a terminal alongside a command
- **THEN** one is allocated for it

#### Scenario: Database session needs no local client
- **WHEN** a user runs the database shell command
- **THEN** an interactive database session opens without a PostgreSQL client being installed locally

#### Scenario: Outside a project
- **WHEN** any of these commands is run outside a project directory
- **THEN** the client reports that in the same terms as its other project-scoped commands

### Requirement: A copy names its remote side, and the direction follows from it
The copy command MUST take a source and a destination, exactly one of which is marked as being on the deployment. The direction of the transfer MUST follow from which one is marked, and MUST NOT be a separate flag the user can set inconsistently with the paths they gave.

Which side is marked MUST be decided by a rule that no local path can satisfy by accident. A path carrying the marker MAY also name a deployment, and MUST then name the one the project names; naming a different one MUST be refused rather than resolved, because the client acts on one deployment and silently ignoring the name would make it look otherwise.

A copy with neither side marked, or with both marked, MUST be refused before connecting, naming which of the two it was. Neither means the user meant a local copy their own shell already does; both means a deployment-to-deployment transfer, which this command does not offer.

A remote path that is not absolute MUST be resolved the way it would be in a session opened by the shell command, so that the two commands agree about what a bare relative path means.

#### Scenario: The marked side is the deployment's
- **WHEN** a user copies a local file to a marked remote path
- **THEN** the file is written into the application container at that path

#### Scenario: The direction reverses with the marking
- **WHEN** a user copies a marked remote path to a local one
- **THEN** the file is read from the application container and written locally

#### Scenario: Neither side is marked
- **WHEN** a user gives two local paths
- **THEN** the client refuses, saying neither path names the deployment, and connects to nothing

#### Scenario: Both sides are marked
- **WHEN** a user gives two remote paths
- **THEN** the client refuses, saying it does not copy between deployments, and connects to nothing

#### Scenario: A local path containing a colon stays local
- **WHEN** a user names a local file whose own name contains a colon
- **THEN** it is treated as a local path, not as a marked one

#### Scenario: A marked path naming another deployment is refused
- **WHEN** a marked path names a deployment other than the one the project names
- **THEN** the client refuses rather than acting on the project's deployment

#### Scenario: A relative remote path agrees with the shell
- **WHEN** a user copies to a relative remote path
- **THEN** it resolves to the same location a shell session would resolve it to

### Requirement: A copy carries a file or a directory tree over the platform's own file transfer
A copy MUST use the file-transfer facility the platform's sidecar serves, which is available on every deployment the client can open a session against and requires nothing to be present in the user's own image.

A directory MUST be copied as the tree beneath it, preserving the relative structure and the file modes of its members, and MUST NOT require a flag to say so. A single file MUST arrive as a single file. Ownership and timestamps are not preserved, and the client MUST NOT imply otherwise.

The client MUST NOT reimplement the transfer protocol, and MUST report the absence of the local tooling it drives as a missing prerequisite naming what to install, as it does for `ssh` itself.

#### Scenario: A copy works against an unmodified deployment
- **WHEN** a user copies to and from a deployment whose image was built by the platform and contains no file-transfer tooling of its own
- **THEN** both transfers succeed

#### Scenario: A directory arrives as a tree
- **WHEN** a user copies a directory containing nested files and an executable
- **THEN** the tree arrives with its structure intact and the executable still executable, with no flag given to ask for recursion

#### Scenario: A binary file round-trips
- **WHEN** a user copies a binary file out of the deployment and back in
- **THEN** the bytes at each end are identical

#### Scenario: Missing local tooling is a named prerequisite
- **WHEN** the copy command runs on a machine lacking the tooling it drives
- **THEN** the client names the missing prerequisite and what to install, and does not fail with an unhandled error

### Requirement: A failed copy is not reported as a successful one
A copy that does not complete MUST exit non-zero and say what did not arrive. A partial transfer MUST NOT be reported as success.

Local conditions the client can see before connecting — a source that does not exist, a destination directory that is not writable — MUST be reported before a connection is attempted, so a predictable failure does not cost a round trip and does not read as a platform problem.

A remote path that does not exist MUST be reported as the deployment's, distinguishably from a local path that does not exist, because the two are told apart only by which side the client says it looked on.

A copy MUST inherit the connection assembly the client's other SSH commands use: the single registered key, the pinned edge host key, and the checks that explain a predictable refusal rather than letting it surface as an opaque one.

#### Scenario: A missing local source is caught first
- **WHEN** a user copies from a local path that does not exist
- **THEN** the client says so and attempts no connection

#### Scenario: A missing remote path names the deployment
- **WHEN** a user copies from a remote path that does not exist
- **THEN** the client reports that the path was not found in the deployment, distinguishably from a local miss

#### Scenario: An interrupted transfer fails
- **WHEN** a transfer is interrupted before it completes
- **THEN** the client exits non-zero and does not report the copy as done

#### Scenario: A copy offers one key and verifies the edge
- **WHEN** a user with several keys in their agent runs a copy
- **THEN** exactly one key is offered to the edge, and the edge's host key is checked against the published value

### Requirement: The client offers exactly one key, the registered one this machine holds
The client MUST present a single identity when it connects: the key recorded for this environment, and no other. It MUST NOT let the user's agent or default key files supply additional identities.

The edge answers *every* offered key with a partial success, so a client that offers several exhausts the server's authentication budget and is refused before reaching the right one. Offering one key is therefore a correctness requirement, not a courtesy.

When no local record exists, the client MUST attempt recovery by fingerprint before giving up, and MUST record what it finds so the next invocation needs no search.

#### Scenario: Only the registered key is offered
- **WHEN** a user with several keys in their agent runs any of these commands
- **THEN** exactly one key is offered to the edge

#### Scenario: A missing record is recovered
- **WHEN** the local record is absent but a registered key's public half is present on this machine
- **THEN** the client finds it by fingerprint, uses it, and records it

#### Scenario: No usable key
- **WHEN** no registered key can be found on this machine
- **THEN** the client says so and names the command that registers one, without attempting a connection

### Requirement: Failures are diagnosed from the platform, never inferred from the refusal
The edge refuses uniformly and discloses nothing about why. The client MUST NOT present a guess at the cause as though it were the cause, and MUST NOT translate a refusal into a specific explanation it cannot support.

Before connecting, the client MUST check what the platform does report — whether the account has a registered key, and whether the deployment is in a state that accepts connections — and MUST explain a predictable failure in those terms rather than letting it surface as an opaque refusal.

When a connection is refused despite those checks passing, the client MUST say that the platform refused, list what it verified, and MUST NOT assert a cause.

#### Scenario: Account with no registered key
- **WHEN** a user whose account has no registered key runs any of these commands
- **THEN** the client explains that before connecting and names the command that registers one

#### Scenario: Deployment that cannot accept connections
- **WHEN** the deployment is in a state the platform does not admit connections for
- **THEN** the client says so rather than attempting a connection that will be refused

#### Scenario: Unexplained refusal is reported honestly
- **WHEN** the platform refuses a connection although the client's checks passed
- **THEN** the client reports the refusal and what it checked, and does not claim a specific cause

#### Scenario: A broken deployment is still reachable
- **WHEN** the deployment's application container is failing but the platform admits connections to it
- **THEN** the client connects, because that is the state these commands exist for

### Requirement: The client verifies the edge rather than trusting it on sight
The client MUST verify the edge's host key against the value the platform publishes, using its own known-hosts store rather than the user's, and MUST NOT accept an unverified host key on first use.

A first connection that trusts whatever answers is the one connection worth attacking, and the platform's host key is stable and knowable, so there is no reason to guess at it.

A host key that does not match the published value MUST be treated as a failure to be reported, never as something to be accepted and recorded.

#### Scenario: First connection is verified
- **WHEN** a user connects for the first time on a machine
- **THEN** the edge's key is checked against the published value and no prompt to trust it appears

#### Scenario: Mismatch is refused
- **WHEN** the edge presents a key other than the published one
- **THEN** the client refuses to connect and reports the mismatch

#### Scenario: The user's own known-hosts is untouched
- **WHEN** the client connects
- **THEN** the user's personal known-hosts file is neither read as authority nor written to

### Requirement: The forwarded address is the platform's, spelled the platform's way
The address the client forwards to MUST be the one the platform reports for that deployment's database, used verbatim. The client MUST NOT reconstruct, normalise, or abbreviate it.

The forward allowlist at the far end matches the destination as the client wrote it and resolves it afterwards, so any difference in spelling produces a refusal that reads like an authorization failure rather than a typo.

#### Scenario: The reported address is used unchanged
- **WHEN** the client opens a forward
- **THEN** the destination it requests is byte-identical to what the platform reported

#### Scenario: A refused forward is explained as such
- **WHEN** a forward is refused by the far end
- **THEN** the client explains that the destination was not permitted, distinguishably from an authentication failure

### Requirement: The proxy prints a usable connection URL and holds the tunnel in the foreground
The forwarding command MUST run in the foreground until interrupted, and MUST print a connection URL addressing the **local** end of the tunnel, carrying the deployment's own database name and credentials.

The URL MUST be correctly encoded, so that a credential containing characters with meaning in a URL yields a URL that parses back to the same values rather than one that silently differs.

The URL MUST go to standard output and everything the client says about itself to standard error, so the URL survives being piped or captured.

#### Scenario: URL addresses the local port
- **WHEN** the forward is established
- **THEN** the printed URL names the local address and port, not the platform's internal one

#### Scenario: URL round-trips
- **WHEN** a credential contains characters requiring encoding in a URL
- **THEN** parsing the printed URL yields exactly the credential the platform reported

#### Scenario: URL is capturable
- **WHEN** the command's standard output is captured
- **THEN** it contains the URL and none of the client's own narration

#### Scenario: Interrupt closes the tunnel
- **WHEN** the user interrupts the command
- **THEN** the tunnel closes and the local port is released

### Requirement: A local port is chosen when one is not given
The forwarding command MUST accept a local port and MUST choose a free one when none is given, reporting which it chose. It MUST NOT fail merely because a conventional default is occupied, and MUST report clearly when a port the user explicitly asked for is unavailable.

#### Scenario: Default port is in use
- **WHEN** no port is given and the conventional one is occupied
- **THEN** the client binds a free port and reports it in the URL it prints

#### Scenario: Requested port is in use
- **WHEN** the user names a port that is unavailable
- **THEN** the client reports that specifically rather than choosing a different one silently

### Requirement: The system SSH client is required and its absence is explained
The client MUST use the system `ssh` executable rather than implementing the protocol, and MUST report its absence as a missing prerequisite naming what to install.

#### Scenario: `ssh` is not installed
- **WHEN** any of these commands runs on a machine with no `ssh` on the path
- **THEN** the client reports the missing prerequisite by name and does not fail with an unhandled error

### Requirement: No credential or key material is written to the terminal beyond the URL
Beyond the connection URL the forwarding command prints for the user to use, a command MUST NOT print, log, or echo a private key, and MUST NOT write credential material to a location the user did not ask for.

#### Scenario: Verbose output stays clean
- **WHEN** any of these commands runs with verbose output enabled
- **THEN** no private key material appears

#### Scenario: The shell commands print no credential
- **WHEN** the shell or database-shell command runs
- **THEN** no database credential is printed

### Requirement: The username is the deployment's id, taken from the platform's record
Every SSH connection the client opens MUST present the deployment's id as the username. The client MUST take that identifier from the deployment record the platform returns and MUST NOT construct it from any other field.

The edge admits one identifier and refuses everything else without saying why, so a client that derives a username by its own rule fails as an authentication refusal — the least diagnosable failure the platform produces. Reading the identifier from the record keeps the client correct across any later change to how the platform assigns it, without a client release.

All four commands MUST derive the username the same way, so no subset of them keeps working after a change to the platform's assignment.

#### Scenario: Every command presents the same username
- **WHEN** a user runs the shell, database-forward, database-session, or copy command
- **THEN** each connects with the deployment's id as the username

#### Scenario: The username is not derived from the deployment's other identifiers
- **WHEN** the client assembles a connection
- **THEN** it uses the id from the deployment record, and neither the deployment's name nor its namespace appears in any part of the username

#### Scenario: A stale identifier is not cached across a change
- **WHEN** the platform's record for a deployment reports a username
- **THEN** the client uses that value for the connection it is about to open, rather than one it derived or stored earlier
