# ssh-sidecar

**The** SSH server: one image in every deployment that offers SSH access at all.
It rides in a tenant's app pod and serves four intentions on one daemon: file
transfer, a shell in the tenant's own application container, the platform's
PostgreSQL tooling, and a port forward to the database pooler that opens no
session at all.

What a given deployment gets follows from **one declared input**,
`FREEPOD_SESSION_ROOT`, and from nothing the container discovers about the pod it
is in. See
[`openspec/changes/archive/2026-09-03-unified-ssh-sidecar/design.md`](../../../openspec/changes/archive/2026-09-03-unified-ssh-sidecar/design.md)
for the design, and [`var/ssh_access.md`](../../../var/ssh_access.md) D2–D4, D6,
D14 and D17 for the access decisions it inherits.

## Architecture in one line

`client → sshpiper (routes by username, authenticates the user's key) → this
sidecar in the app pod → files from its own mount, or a shell, files, psql and a
forward against the application container`.

## Runtime configuration contract

Everything per-deployment arrives as an environment variable. None of it is
secret from the pod — the trusted key is a *public* key, and the database
details are already in the application container's environment — so there is
nothing here that wants a mounted file.

**The container validates all of them and exits non-zero naming the offending
variable if a required one is missing or any is malformed**, rather than
starting a server that refuses every connection: that failure is
indistinguishable from a network fault and gets diagnosed as one.

| Variable                                             | Meaning                                                                                                                                                                                                                                          |
|------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `FREEPOD_AUTHORIZED_KEYS`                            | The public keys the server trusts, one per line. In normal operation this is the single public key of the platform's SSH edge — the tenant's own keys are checked by sshpiper on the downstream leg, never here. Validated with `ssh-keygen -l`. |
| `FREEPOD_PERMIT_OPEN`                                | *Optional.* The forward allowlist: whitespace- or comma-separated `host:port`. Rendered as sshd's `PermitOpen`; absent, the server writes `PermitOpen none` and refuses every forward. See *Spelling the allowlist* below.                        |
| `FREEPOD_RELEASE_ID`                                 | The release the pod belongs to, as the uuid the log pipeline keys a stream on. Recorded on the startup line. The chart projects `caelus.releaseId` here directly (D17).                                                     |
| `FREEPOD_RELEASE_NUMBER`                             | The same release as the client shows it — the number in `freepod releases` — reported by the session banner. The chart projects `caelus.releaseNumber` here directly (D17).                                                                      |
| `FREEPOD_LOGIN_USER`                                 | The account the SSH edge authenticates the upstream leg as: the **deployment name**. Added as a second uid-0 account at startup. See *The login account* below.                                                                                  |
| `FREEPOD_SESSION_ROOT`                               | **The one thing a product declares.** `app-container`, or `volume:/<absolute path>` naming where in the session the product's data appears. No default and no fallback: a container given none exits. See *The session root* below.               |
| `PGHOST` `PGPORT` `PGUSER` `PGPASSWORD` `PGDATABASE` | *Optional as a set, all-or-nothing individually.* The deployment's database, in libpq's own variable names so that a bare `psql` connects with no wrapper and no arguments. `PGSSLMODE` and `PGAPPNAME` are passed through if set. See *No database* below. |

The server listens on **2222**, the platform's sidecar-port convention that the
tenant NetworkPolicy admits from the SSH edge.

### The session root

Everything a session may do follows from this one input, and it is checked
against the **declaration** rather than inferred from what the pod exposes.

`volume:` requires the chart to have mounted the product's volume at
`/srv/session<path>`; a container whose chart mounted it elsewhere exits at
startup naming the path it looked at, rather than opening an empty session that
reads like missing data.

`app-container` requires `shareProcessNamespace: true` on the pod. Without it
the container still starts and serves — forwarding and the toolbox work — and a
session that needs the application container says what is missing.

### The login account

The edge authenticates the upstream leg as the **deployment name**, not as
`root`. It has exactly one username convention — the deployment name — which it
derives from the deployment's own record, reading no cluster object, so no
product can choose a different one and the edge stays ignorant of what any
deployment's sessions are rooted at (see
[`ssh-auth/README.md`](../../../ssh-auth/README.md) § *Coupling*).

This server needs uid 0 — the dispatcher reads another container's process
filesystem and enters it — so rather than teaching the edge a second convention,
the entrypoint adds `FREEPOD_LOGIN_USER` as a **second uid-0 account**. `root`
stays first in `/etc/passwd`, so `getpwuid(0)` still resolves to `root` and
`whoami`, `ls -l` and friends are unchanged; the name exists only to be logged in
as, and `root` still works.

Its password field is `*`, not `!`. That distinction is load-bearing and easy to
get wrong: `!` is the *locked* marker `useradd` writes by default, and with
`UsePAM no` sshd's `allowed_user()` refuses a locked account **before it looks at
a key**, so the account would exist and every publickey attempt would still be
denied. Both mean "no password login"; only one of them permits keys.

Without this variable the container exits at startup. Getting it wrong instead —
the account absent while the server runs — produces `Invalid user <deployment>` in
this log and `Permission denied (publickey)` at the client, which reads as an
authorization problem rather than a missing account.

### Spelling the allowlist

`PermitOpen` matches the destination **as the client wrote it**, and the sidecar
resolves that name afterwards. So the value rendered here and the value the CLI
passes to `ssh -L` must agree byte for byte: `pooler.caelus.svc:6432` and
`pooler.caelus.svc.cluster.local:6432` are not interchangeable, and a mismatch
produces a refusal that reads like an authorization failure rather than a typo.
Wildcard ports are rejected — an entry that opens every port on a host is not an
allowlist.

What is never optional is the directive. sshd's default is to permit forwarding
to anywhere, so a deployment with nothing to allow gets `PermitOpen none`
written out rather than the line left off: tenant egress reaches the public
internet on every port, and an unconstrained forwarder would be an authenticated
open TCP relay originating from the platform's own address.

### No database

A product without relational storage supplies none of the `PG*` variables and
runs this image unchanged. The toolbox is a facility the image offers, not a
precondition it imposes — a shell in the application container is worth having
either way, and refusing to start over a missing extra would deny the whole
session to get it.

What that deployment loses is exactly the two database-derived facilities: the
dispatcher declines `psql` and its siblings by name, saying the deployment has
no database, and there is nothing to forward to so every forward is refused.
Everything else — the shell, remote commands, file transfer, the banner — is
the same server.

**A partial set is a different thing from an absent one** and aborts startup
naming both halves. It means the projection that should have supplied the
variables is broken, and a container that started anyway would surface that as a
connection error inside `psql`, at the moment someone needed the database and
furthest from the cause.

## Where a session lands

The dispatcher runs as sshd's `ForceCommand`, so every session passes through it
and no session can avoid it. Port forwarding is a `direct-tcpip` channel, opens
no session, and therefore never reaches it — which is also why the dispatcher
cannot break forwarding: a deployment that must forward nothing is given an
empty allowlist rather than a dispatcher that refuses, because the dispatcher is
never asked.

| The client runs                      | `app-container`                                                 | `volume:/<path>`                       |
|--------------------------------------|-----------------------------------------------------------------|----------------------------------------|
| `ssh <deployment>`                   | a login shell in the **application container**                  | refused, naming the session root       |
| `ssh <deployment> psql …`            | the **sidecar**, where the tools and the connection details are | refused, naming the session root       |
| `ssh <deployment> '<anything else>'` | the **application container**                                   | refused, naming the session root       |
| `scp` / `sftp`                       | **this image's own `sftp-server`**, chrooted into the app       | the same, chrooted into the jail       |
| `ssh -N -L …`                        | nowhere — the dispatcher is not involved                        | refused: no allowlist is supplied      |

The session root is read **first**, before the command is looked at, so a
refusal is a property of the deployment rather than of what the dispatcher could
find.

The platform allowlist is `psql`, `pg_dump`, `pg_dumpall`, `pg_restore` and
`pg_isready`, decided on the **command** and never on arguments a client
controls: `ssh <deployment> '/bin/echo psql'` runs `/bin/echo` in the
application container. On a deployment with no database they are declined rather
than run, and a command given as a path reaches the application container as any
other would.

The allowlist routes; it does not confine. A developer who reaches this server
is authenticated and gets a shell in the application container as the user the
application runs as — root, for most images — which already shares the pod's
network namespace — so the sidecar is not a boundary
they are being held outside of, and `PermitOpen` constrains forwarding rather
than egress in general.

### Identifying the application container

Candidate processes are grouped by cgroup. The dispatcher's own cgroup is
excluded, and so is the pod's infrastructure process — the `pause` binary every
CRI runs. Exactly one cgroup must remain, and its lowest-numbered process is the
application.

Simpler rules are wrong in ways that matter. Under Kubernetes with a shared
process namespace PID 1 is the infrastructure container; under the test harness
there is none and the application *is* PID 1. A cgroup rule is correct in both,
which is what lets the harness prove the production behavior rather than an
approximation of it.

**Ambiguity is refused, not resolved.** More than one candidate, or none, ends
the session with a message naming the likely cause. A developer placed in the
wrong container would debug something that is not their application and draw
conclusions from it; a refusal costs them a question, and a wrong container costs
them an afternoon. Multi-container products are consequently not supported on
an application-container session root.

### Entering it as the user it runs as

The dispatcher reads the application container through `/proc/<pid>` — its
root, its environment, its working directory — and the kernel guards all of it
with a ptrace access check. Root passes that check for a process of another uid
or gid only by holding `CAP_SYS_PTRACE`, which Pod Security `baseline` refuses.
So once it has identified the application, the dispatcher starts over under that
process's uid, gid and supplementary groups (`setpriv`), keeping
`CAP_SYS_CHROOT` as an ambient capability because entering is a chroot. An
application running as root is entered as root, as before; one running as
`USER node` is entered as `node`, which is what `kubectl exec` does too.

The transfer program lives in the sidecar, out of reach of those credentials,
so for a transfer the dispatcher opens the session jail as a descriptor before
switching and runs the program through `/proc/self/fd/3`. The jail holds that
program and nothing else, so a transfer that keeps it open exposes nothing of
the sidecar's. A session keeps `CAP_SYS_CHROOT`, which is strictly less than a
session in a root application holds.

One application cannot be entered this way: a process that switched its user in
place without then starting a new program, which the kernel marks as closed to
every other process. The session says so. Starting the program as its final
user, or `exec`ing it after the switch as `gosu` and `su-exec` do, avoids it.

### What the application image has to provide

A **shell** session runs in the tenant's own image, so what it can do is a
property of that image: a distroless image ends the session with a message
saying so. `docker exec` and `kubectl exec` fail here too; the image is the
user's own and adding a shell to it is a change they can make. The session is
*not* redirected into the sidecar, which would have them debugging a container
that is not theirs.

**File transfer** needs nothing of the tenant's, with one exception: the
image's `/etc/passwd` must name the user the application runs as, because the
transfer program resolves the user it runs as before it does anything else. A
hand-built image with no `/etc/passwd`, or an application started as a bare uid
its image does not name, cannot host one; a shell and remote commands still
work there.

### The banner

Interactive sessions print `freepod: release <number>` on **standard error** —
the number `freepod releases` shows, not the uuid. A banner naming the uuid
answers the question in a spelling the user cannot look up; the uuid stays on the
startup line, where it is read next to the log stream it keys.

Standard output is a protocol channel for file transfer and dump streams, so a
banner written there corrupts the transfer and produces a data error far from its
cause. It is suppressed entirely when no terminal was allocated.

The release identity comes from configuration rather than from the pod's name or
from timing: during a rollout two releases' pods both serve and the connection
lands on one of them at random, so someone running `freepod shell` to find out
why their new release is broken has roughly even odds of landing in the previous,
working one and concluding nothing is wrong.

## What is in the image, and what is not

- **Debian trixie** with **`postgresql-client-18`** pinned to `18.6-1.pgdg13+2`
  from the PostgreSQL project's own apt repository, whose signing key is vendored
  here as `pgdg-archive-key.asc`. Neither distribution ships 18 in a pinnable
  release: Alpine 3.22 offers 17, and trixie's own `postgresql-client` resolves
  to `17+278`. The client must not be older than the tenant cluster's server or
  `pg_dump` aborts outright, which is not fixable from the client — which is the
  whole reason the toolbox is here rather than on the developer's laptop.
- **OpenSSH server**, configured at startup: public key only, no chroot,
  `AllowTcpForwarding local` with the allowlist, no remote forwarding, no agent
  forwarding, no X11, no gateway ports, and the dispatcher as `ForceCommand`.
- **An Ed25519 host key generated per container start**, never persisted and
  never baked in. Only Ed25519, which costs milliseconds: an RSA-4096 key costs
  seconds before anything listens and buys nothing here — the identity a
  developer verifies is the platform edge's, and the hop from the edge to this
  server does not pin this key.
- **No credential, key, password or tenant data of any kind.** Everything needed
  to authenticate a session arrives at runtime.

It runs as **root**, which is what reading and entering another container's
process filesystem requires, and what reads a product's data whatever uid the
application wrote it as — sound only because a volume session cannot write. It takes no capability beyond what the pod grants,
mounts nothing, and needs no privileged mode. `CAP_SYS_CHROOT` is in the default
set and is what entering the application container needs; the pod supplies
`shareProcessNamespace: true`, and `CAP_SYS_PTRACE` — needed only by `strace`,
`gdb` and `py-spy` — is not granted under Pod Security `baseline`. When either
is absent the container still starts and serves, and says so when a session
depends on it.

## Testing

No cluster. `docker run --pid=container:<name>` reproduces the shared process
namespace, and the harness needs only docker, ssh and bash:

```bash
./test/run-tests.sh                  # build from this context and test it
./test/run-tests.sh --image REF      # test an already-built or pulled image
```

It stands up a PostgreSQL server, two forward targets, an ordinary application
container **carrying no transfer tooling at all**, a distroless one, a sidecar
with no application beside it, a sidecar with no database and no allowlist, a
volume-rooted sidecar over a read-only mount owned by another uid, and a
volume-rooted sidecar in a pod that *does* share a process namespace and *does*
hold database variables — which must change nothing, because the declaration
decides. It then asserts every behavior above. The negative cases are each a security
property rather than a feature, so they are asserted rather than assumed:
password authentication refused, unknown key refused, unlisted forward
destination refused, remote and agent forwarding refused, a command's
metacharacters never expanded by the dispatcher, and startup aborted for each
missing or malformed input.

If the harness runs inside a container on the same docker daemon — a devcontainer
— published ports land on the daemon's host and are unreachable from it, so it
joins the test network and addresses containers directly instead. That is
detected, not configured.

## Build and publish

**amd64 only**, as [`products/custom/builder`](../../custom/builder/) is: the
cluster node is amd64 and multi-arch is an explicit non-goal, so the Dockerfile
fails the build on any other architecture rather than producing an image whose
PostgreSQL client cannot exec.

The version lives in [`VERSION`](./VERSION) and nowhere else. It is the single
input the publish target reads:

```bash
./scripts/build-images.sh --ssh-sidecar
```

**A published tag is never overwritten.** A change to the image is a new version:
bump `VERSION`, publish, and repoint the chart that names it. The script enforces
this rather than trusting anyone to remember — it refuses to push a version the
registry already holds.

**CI publishes it on merge to master**, running the same target with
`--skip-if-published`, which turns that refusal into "nothing to do". So a push
happens exactly when `VERSION` names a version the registry does not have, and
every other merge is a no-op rather than a red build. Publishing by hand is still
the right move when you want to get an image out ahead of a merge — and the bare
`--ssh-sidecar` keeps failing loudly there, which is what you want when you
thought you had bumped the version and had not.

The sidecar is deliberately *not* in `--all`. The images that target covers are
platform Deployments on moving tags, re-pushed on every merge and picked up by
restarting their pods; an immutable tag in that set would fail every merge that
did not bump it.

**The image's version is its own, independent of the chart's.** The coupling runs
one way: the image reference lives in the chart, so no new image reaches a
deployment except through a chart upgrade — but charts change constantly for
reasons that never touch the image. Making the two numbers agree would mean
either rebuilding a byte-identical image on every chart edit or letting them
drift while still claiming to agree, and a promise that holds most of the time is
worse than no promise.

Publishing does not roll anything out. `./scripts/rollout.sh` restarts the
platform's own Deployments and knows nothing about tenant pods; this image
reaches them through a chart version bump fanned out by the reconciler.

### First publish

The first publish is a manual one: the GHCR package is created by its first push
**at GHCR's default visibility, which is private**, and CI's `GITHUB_TOKEN`
cannot change that. Nothing in this platform configures an `imagePullSecret`
(see [`tf/app/README.md`](../../../tf/app/README.md) § *Non-secret variables*, which
documents the same trap for the API and UI images), so a private package fails
the pull tenant-side with an `ImagePullBackOff` that names no cause. Set the
package to public after the first push and confirm with an unauthenticated pull.

## Two obligations this places on the chart that adopts it

1. **A render assertion tying the chart's referenced tag to `VERSION`**, in the
   shape of `api/tests/test_ssh_chart_contract.py`. Without it a chart can
   reference a version nobody built.
2. **`imagePullPolicy: IfNotPresent` on the sidecar container**, stated
   explicitly. With an immutable tag, tag and content are one to one, which makes
   caching correct rather than accidental.
3. **A volume session root mounted at `/srv/session<path>`, read-only.** The jail
   path is shared between this image and the library chart the same way the
   `-ssh` Service name is shared with the resolver, and read-only is the whole of
   the guarantee: nothing inside the container is trusted to provide it.
