# ssh-session-dispatcher Specification

## Purpose

One SSH server has to serve three different intentions: a developer wanting a shell in
their own application, a client running the platform's database tooling, and a plain port
forward that carries no session at all. This capability defines the dispatcher that
decides which of those a connection gets, how it identifies the application container to
enter, what it does when that container cannot host a shell, and how it tells the
developer which release they landed on without corrupting the sessions that carry data.

## Requirements

### Requirement: A shell is served only where the session root is the application container
When a session requests no command and the declared session root is the application container, the dispatcher MUST place the user in that container: its filesystem, its executables, and its environment, as seen from the process running there.

A shell in the sidecar's own filesystem, holding none of the user's code, does not serve that request and MUST NOT be offered in its place.

When the declared session root is a mounted path, the dispatcher MUST refuse the session and say so. A session rooted at a read-only view of a product's data has no shell to offer: there is no code of the user's to run there, and the mount is not theirs to execute in. The refusal MUST name the reason rather than surfacing as an execution failure.

The refusal MUST be decided on the declaration. The dispatcher MUST NOT decide it by looking for an application process, because a pod that gained a shared process namespace for an unrelated reason would then begin granting shells it was never meant to.

#### Scenario: Shell sees the application's filesystem
- **WHEN** a user opens a session with no command against an application-rooted deployment whose application container is running
- **THEN** the resulting shell reads the application container's filesystem, not the sidecar's

#### Scenario: Shell sees the application's environment
- **WHEN** that shell inspects its environment
- **THEN** it carries the environment variables the application process was started with

#### Scenario: A volume-rooted session has no shell
- **WHEN** a user opens a session with no command against a volume-rooted deployment
- **THEN** the dispatcher refuses, naming the reason, and opens no session

#### Scenario: The refusal does not depend on the pod
- **WHEN** a volume-rooted deployment's pod shares a process namespace with an application container
- **THEN** a session with no command is still refused

### Requirement: The application process is identified by a documented, deterministic rule
The dispatcher MUST identify which process belongs to the application container by an explicit rule, not by a guess that happens to work. The rule MUST distinguish the application's processes both from the sidecar's own and from the pod's infrastructure process, and MUST be documented alongside the implementation.

When the rule cannot identify exactly one candidate, the dispatcher MUST say so and MUST NOT pick arbitrarily. Entering the wrong container silently is worse than refusing: a developer would debug something that is not their application and draw conclusions from it.

#### Scenario: Single application container is identified
- **WHEN** the pod has one application container beside the sidecar
- **THEN** the dispatcher identifies that container's process

#### Scenario: Sidecar's own processes are excluded
- **WHEN** the dispatcher enumerates candidates
- **THEN** processes belonging to the sidecar itself and to the pod's infrastructure container are not among them

#### Scenario: Ambiguity is refused, not guessed
- **WHEN** the rule identifies more than one candidate
- **THEN** the dispatcher reports the ambiguity and does not enter any of them

#### Scenario: No candidate
- **WHEN** no application process can be identified, because it is not running or the process namespace is not shared
- **THEN** the dispatcher reports that plainly, naming the likely cause

#### Scenario: An application running as another user is identified
- **WHEN** the application process runs as a user other than the sidecar's
- **THEN** the rule identifies it from what the kernel shows every process, reading nothing it withholds from another user

### Requirement: A session in the application container runs with the application's credentials
A session the dispatcher places in the application container — a shell, a command, or a file transfer — MUST run under the uid, gid and supplementary groups of the application process it entered, whichever user that is, and MUST NOT depend on a capability Pod Security `baseline` refuses.

The kernel guards another process's filesystem, environment and working directory with a ptrace access check, which root passes for a process of a different user only by holding `CAP_SYS_PTRACE`. A dispatcher that entered as root would reach only applications that run as root, and images that declare a user of their own are common. Taking the application's credentials passes the check without the capability, and is what `docker exec` and `kubectl exec` do: files a session creates belong to the application, and a session can do in the container what the application can.

Entering needs `CAP_SYS_CHROOT`, and a session MAY keep it. It MUST hold no other capability the application's user does not.

When the application process cannot be entered under its own credentials — it changed its user without then starting a new program, which the kernel treats as closing it to other processes — the dispatcher MUST say so rather than report a missing process or a missing shell.

#### Scenario: An application running as a non-root user is entered
- **WHEN** a user opens a session against an application whose process runs as a non-root user, beside a sidecar holding no `CAP_SYS_PTRACE`
- **THEN** the session opens in the application container and runs as that process's uid, gid and supplementary groups

#### Scenario: An application running as root is entered as root
- **WHEN** the application process runs as root
- **THEN** the session runs as root

#### Scenario: A transferred file belongs to the application
- **WHEN** a client uploads a file to an application that runs as a non-root user
- **THEN** the file is owned by that user

#### Scenario: No capability beyond entering
- **WHEN** a session in an application that runs as a non-root user inspects its capabilities
- **THEN** it holds none other than `CAP_SYS_CHROOT`

#### Scenario: A process closed to entry is reported
- **WHEN** the application process changed its user in place, without starting a new program
- **THEN** the dispatcher refuses the session, naming that cause

### Requirement: The platform's database tooling is served only where the session root is the application container
A session requesting one of the platform's own tools — the PostgreSQL client and dump/restore tooling — MUST run it in the sidecar, where those tools live and where their connection details are, and MUST do so only where the declared session root is the application container.

The set of commands treated this way MUST be an explicit allowlist. Membership MUST be decided on the requested command itself and MUST NOT be inferrable from arguments a client controls.

Two separate conditions govern these commands and MUST be checked in order. Whether the tooling is offered at all follows from the declared session root: a volume-rooted session MUST decline it by name, whatever the container's environment holds. Whether there is a database to reach follows from the connection details: an application-rooted deployment without them MUST decline by naming the absence of a database, rather than running the tool and leaving the client to interpret a connection error.

Checking the environment alone would conflate the two, and would grant a database shell to any deployment that came to hold connection details for another reason.

Declining is still a routing decision on the command, so a command given as a path reaches the session root as any other does.

#### Scenario: Database client runs in the sidecar
- **WHEN** a session against an application-rooted deployment requests the PostgreSQL client
- **THEN** it runs in the sidecar and connects to the deployment's database

#### Scenario: Dump runs in the sidecar and streams
- **WHEN** such a session requests a dump
- **THEN** the dump runs in the sidecar and its output is delivered to the client unmodified

#### Scenario: Allowlist is not argument-driven
- **WHEN** a session requests a command whose arguments resemble an allowlisted tool but whose command is not one
- **THEN** it is not treated as a platform command

#### Scenario: A volume-rooted session is declined the tooling
- **WHEN** a session against a volume-rooted deployment requests a database tool
- **THEN** it is declined by name, and it is declined whether or not connection details are present in the container

#### Scenario: A platform command on a deployment with no database is declined
- **WHEN** a session against an application-rooted deployment with no database requests a database tool
- **THEN** the request is refused with a message naming the absence of a database, and no client connection error is produced instead

### Requirement: Any other command runs in the application container, and nowhere else
A session requesting a command that is not on the platform allowlist MUST run it in the application container when the declared session root is that container, so that ordinary remote-command behavior holds.

When the declared session root is a mounted path, the dispatcher MUST refuse the command and name the reason. There is no container to run it in, and running it in the sidecar would execute it somewhere the requester did not ask for.

#### Scenario: Arbitrary command runs where the application is
- **WHEN** a session against an application-rooted deployment requests a command that is not on the platform allowlist
- **THEN** the command runs in the application container

#### Scenario: A volume-rooted session runs no command
- **WHEN** a session against a volume-rooted deployment requests any command
- **THEN** it is refused by name, and nothing runs in the sidecar

### Requirement: File transfer is served from the sidecar, rooted at the session root
A session requesting file transfer MUST be served by the sidecar's own file-transfer tooling, confined to the declared session root, on every deployment that has a sidecar. The dispatcher MUST NOT look for a helper in the application container's filesystem and MUST NOT make the request's success depend on what a tenant's image contains.

This is the one session path both session roots serve, and it MUST be reached the same way for both: an application-rooted session transfers within the application container's filesystem, a volume-rooted session within its mount, and the difference is the root rather than the mechanism. One path used by every session is a path whose failures are found immediately.

#### Scenario: Transfer works against a minimal application image
- **WHEN** a client copies a file to an application-rooted deployment whose image contains no file-transfer helper
- **THEN** the file appears in the application container's filesystem

#### Scenario: Transfer on a volume-rooted deployment reads the mount
- **WHEN** a client lists and downloads from a volume-rooted deployment
- **THEN** it reads the mounted data, and cannot reach a path outside it

#### Scenario: One mechanism for both roots
- **WHEN** file transfer is served for either session root
- **THEN** the same sidecar-owned tooling serves it

### Requirement: The command is never re-interpreted by a shell
The requested command MUST be passed to the target without being re-evaluated by a shell in a way that would let its text expand into further commands. The dispatcher MUST treat the requested command as data.

The requested command is attacker-influenced input arriving over the network at an authenticated but unprivileged boundary; re-evaluating it is a command injection.

#### Scenario: Shell metacharacters are not expanded by the dispatcher
- **WHEN** a session requests a command whose text contains shell metacharacters, substitutions, or separators
- **THEN** the dispatcher does not evaluate them as additional commands

### Requirement: Port forwarding never reaches the dispatcher
A connection that requests only port forwarding opens no session, so the dispatcher MUST NOT be involved in it and MUST NOT be able to prevent it. Forwarding is constrained by the server's own configuration, not by this dispatcher.

#### Scenario: Forwarding works with no session
- **WHEN** a client opens a connection requesting only a permitted port forward and no session
- **THEN** the forward is established without the dispatcher running

#### Scenario: A broken dispatcher does not break forwarding
- **WHEN** the dispatcher would fail for a session on this pod
- **THEN** a forwarding-only connection is unaffected

### Requirement: An application container that cannot host the session fails plainly
The application container may be a minimal image containing no shell, or may not contain the requested executable. The dispatcher MUST report that plainly and exit non-zero, naming the cause and the container it applies to. It MUST NOT place the session anywhere else.

This matches `docker exec` and `kubectl exec`, which fail the same way for the same reason, and it is what a developer expects: the contents of the application image are theirs, and adding a shell to it is a change they can make. Silently landing them in a different container would be worse than the failure — they would inspect something that is not their application and conclude from it.

The message MUST name the cause rather than surfacing a raw execution failure, which reads as a platform fault rather than as a property of the user's own image.

#### Scenario: Minimal application image
- **WHEN** a user opens a session with no command against a deployment whose application image contains no shell
- **THEN** the dispatcher reports that the application image provides no shell, exits non-zero, and opens no session elsewhere

#### Scenario: Requested command is absent from the application container
- **WHEN** a session requests a command the application container does not contain
- **THEN** the dispatcher reports that, exits non-zero, and does not run the command in the sidecar

#### Scenario: Failure is explained, not raw
- **WHEN** either failure occurs
- **THEN** the message names the cause rather than surfacing an executable-not-found error

### Requirement: Every session reports which release it landed on
The dispatcher MUST report the identity of the release whose pod the session reached, taking it from configuration supplied to the container rather than deriving it by observation.

During a rollout, two releases' pods can both be serving and the connection lands on one of them unpredictably. Without this, a developer investigating a broken release can be shown a working one and conclude nothing is wrong.

The identity reported MUST be the release **number** the client shows its user, not the platform's internal identifier for that release. The banner exists to answer "which release did I land on", and an answer spelled in an identifier that appears nowhere in the client's own output leaves the user unable to act on it. The internal identifier is reported elsewhere by the container, where it is read next to the logs it keys.

#### Scenario: Session states its release
- **WHEN** a user opens an interactive session
- **THEN** the session reports the release identity it reached

#### Scenario: The reported identity is the one the client shows
- **WHEN** a user compares the identity a session reports against the releases the client lists
- **THEN** it is one of the numbers listed there, not an identifier absent from that listing

#### Scenario: Identity comes from configuration
- **WHEN** the release identity is reported
- **THEN** it is the value supplied to the container, not one inferred from the pod's name or from timing

### Requirement: The banner never corrupts a session that carries data
The banner MUST NOT be written to the session's standard output, and MUST NOT appear in non-interactive sessions.

File transfer and dump streams use standard output as a protocol channel: text written there corrupts a transfer, and the resulting failure appears as a mysterious data error far from its cause.

#### Scenario: File transfer is unaffected
- **WHEN** a user copies a file over a session
- **THEN** no banner text appears in the transferred data and the transfer succeeds

#### Scenario: Dump output is unaffected
- **WHEN** a session streams a database dump
- **THEN** the dump output contains no banner text and restores cleanly

#### Scenario: Interactive session still sees it
- **WHEN** a user opens an interactive session
- **THEN** the banner is visible to them
