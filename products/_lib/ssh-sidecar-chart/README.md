# ssh-sidecar library chart

Adds SSH access to a Caelus deployment. The deployment gets a username (= Helm
release name), and its owner authenticates with an SSH key registered on their
account, connecting to the platform endpoint (`freepod.eu:22` /
`dev.freepod.eu:23`).

One server serves every product: the platform's own
[ssh-sidecar image](../ssh-sidecar-image/README.md). **A product declares
exactly one thing — its session root — and everything else follows from it.**

|                    | `volume:/<path>`                                   | `app-container`                                       |
|--------------------|----------------------------------------------------|-------------------------------------------------------|
| Session rooted at  | a read-only mount of the data the product exposes  | the filesystem the tenant's own code runs in          |
| For                | products with user-visible data                    | `custom`, whose owner wrote the code in the pod       |
| Session offers     | file transfer, and nothing else                    | a shell, remote commands, file transfer               |
| Writable           | no — the mount is read-only                        | as the application's own mounts allow                 |
| Tooling            | none                                               | PostgreSQL 18 client and dump/restore                 |
| Forwarding         | refused (no allowlist is supplied)                 | to the deployment's database, allowlisted             |
| Pod needs          | the volume, mounted by this chart                  | `shareProcessNamespace: true`                         |
| Renders            | sidecar, Service                                   | sidecar, Service                                      |

It is a Helm **library chart** — it renders no resources on its own. A product
wrapper chart depends on it and calls its named templates.

Spec: [ssh-chart-contract](../../../openspec/specs/ssh-chart-contract/spec.md),
[sftp-edge-routing](../../../openspec/specs/sftp-edge-routing/spec.md) ·
Rationale: [unified-ssh-sidecar](../../../openspec/changes/archive/2026-09-03-unified-ssh-sidecar/design.md),
[ssh-grpc-auth-plugin](../../../openspec/changes/archive/2026-08-30-ssh-grpc-auth-plugin/design.md)

## One helper set

```
ssh-sidecar.resources      the Service, and nothing else
ssh-sidecar.sidecar        the sidecar container, to splice into a pod
ssh-sidecar.service        \
ssh-sidecar.podSelector     >  shared internals
ssh-sidecar.labels         /
ssh-sidecar.sessionJail    where a volume session is rooted; see below
```

## Architecture in one line

`client → sshpiper (asks the SSH auth resolver who this is and where it goes)
→ this deployment's sidecar → its data mount, or its application container`.

The chart renders no routing object: the edge resolves the route and the user's
key from the platform database on every connection (`daemons/ssh-auth/`).

The sidecar rides **inside the app pod** — for a volume root because RWO PVCs
can only be shared by containers in the same pod, and for an application root
because a shared process namespace is what lets it reach the application at all.

## The `-ssh` naming convention is shared with the resolver

`ssh-sidecar.service` names the Service `<release>-ssh`. That name is **not this
chart's to choose**: the SSH edge derives a deployment's upstream address from
it by string convention, in
[`daemons/ssh-auth/resolve.go`](../../../daemons/ssh-auth/README.md#the--ssh-naming-convention-is-shared-with-the-charts).
**Neither side may change it alone.**

The coupling is invisible in both directions — the resolver names a Service it
never validates, and this chart names a Service nothing in its own release
consults — so a unilateral change breaks nothing at build time and produces
deployments that authenticate successfully and then reach nothing.

The **port** (2222) is shared the same way, and the edge never has to know
which one a deployment declared.

## The session jail is shared with the image

`ssh-sidecar.sessionJail` is `/srv/session`, and a volume mount is rendered at
`<jail><path>` — `volume:/data` is mounted at `/srv/session/data`.

## What it renders

`ssh-sidecar.resources` emits the Service and **nothing else**, whatever the
session root. `ssh-sidecar.sidecar` emits the container.

**Required values.** `caelus.ssh.platformPublicKey` is the SSH edge's public
key, the only key the sidecar trusts. `caelus.releaseNumber` is the release as
`freepod releases` shows it, which the session banner reports, and
`caelus.releaseId` is the uuid the sidecar records on its startup line. The
reconciler injects all three for every deployment.

**Required param.** `sidecar` takes `image`, pinned to an exact version and
supplied as a **system** value — a tenant-settable reference would let a tenant
substitute the container that holds the platform's trusted key and reads their
data. See [the image's README](../ssh-sidecar-image/README.md).

## Wiring it into a product

### 1. Add the dependency (`Chart.yaml`)

```yaml
dependencies:
  - name: ssh-sidecar
    version: "0.5.0"
    repository: "file://../../_lib/ssh-sidecar-chart"
```

Then `helm dependency build ./chart` (vendors it into `charts/`).

If your chart has a `.helmignore` ignoring `*.tgz`, **anchor it** (`/*.tgz`) —
unanchored it also strips the vendored dependency out of `charts/`.

### 2. Render the Service

`templates/ssh.yaml`:

```yaml
{{ include "ssh-sidecar.resources" (dict "root" .) }}
```

Products whose sidecar rides in an upstream subchart's pod must pass `selector`
so the Service targets that pod rather than every pod carrying the instance
label:

```yaml
{{ include "ssh-sidecar.resources" (dict "root" . "selector"
     (dict "app.kubernetes.io/instance" .Release.Name
           "app.kubernetes.io/name" "nextcloud")) }}
```

### 3. Splice in the sidecar

**A volume session root**, with the volume already declared by your pod:

```yaml
      containers:
        # ... app containers ...
        {{- include "ssh-sidecar.sidecar" (dict "root" . "image" .Values.sshSidecarImage
             "sessionRoot" "volume:/data"
             "mounts" (list (dict "volume" "data" "path" "/data"))) | nindent 8 }}
```

**An application-container session root** — note `shareProcessNamespace`, which
no container helper can set for you:

```yaml
    spec:
      shareProcessNamespace: true
      containers:
        # ... app container ...
        {{- include "ssh-sidecar.sidecar" (dict "root" . "image" .Values.sshSidecarImage
             "sessionRoot" "app-container") | nindent 8 }}
```

If an upstream chart supports neither `extraContainers` nor a sidecar hook, SSH
is not offered for that product (document it and move on).

## Rules (do not skip)

### Whatever the session root

- **The Service name and port are not yours to change.** See *The `-ssh` naming
  convention* above. Overriding `serviceName` makes the deployment unroutable.
- **Reachability is deliberately independent of application health.** The
  Service sets `publishNotReadyAddresses: true`, so its endpoints include the
  deployment's pod whenever that pod exists, ready or not. This is not an
  oversight to tidy up in a refactor: the Service fronts an administrative
  sidecar, not the application, and a tenant whose app is crash-looping is
  exactly the tenant who needs to get in. Dropping the flag is silent —
  everything works until an app crash-loops, which is when nobody is looking at
  the Service. The application's own Service is untouched and still excludes
  unready pods.
- **The sidecar is liveness-probed, and that is load-bearing.** With readiness
  no longer gating routing, the `livenessProbe` (a `tcpSocket` check on 2222) is
  the only thing that stops connections being routed to a wedged `sshd`. Neither
  probe may reference the application container, the mounted data, or any
  credential — a sidecar whose mount is unhappy is still worth reaching, since
  that may be the thing being debugged.
- **Nothing secret may ever be mounted into the sidecar.** It holds one public
  key and its own generated host key, and that is what makes it safe to place
  beside a tenant's containers.
- **The image reference is a system value, pinned to an exact version.** Never a
  moving tag: the version a pod runs would become a function of when it last
  restarted and what its node had cached.
- **No container may request a capability.** Tenant namespaces enforce Pod
  Security `baseline`, which refuses every non-default capability at admission;
  a pod asking for one never schedules, and the Helm upgrade fails with
  `violates PodSecurity "baseline:latest"` rather than anything naming the
  chart. Everything the sidecar does needs only the default set.

### A volume session root

- **Never mount a database volume.** Only volumes holding user-visible data
  (uploads, media, config the user should see). Postgres/MariaDB/Valkey data
  dirs are off-limits — exposing a live DB data dir is a corruption and
  data-exfiltration footgun. When in doubt, expose nothing.
- **Nothing to expose renders nothing.** A product with no user-visible data
  must not call these helpers at all: its sidecar would offer an empty session.
  `ssh-sidecar.sidecar` fails the render on empty `mounts` rather than letting
  that happen quietly.
- **Read-only is the mount, and nothing else is trusted to provide it.** Every
  mount is rendered `readOnly: true`. A write is `EROFS` regardless of the uid
  the session runs as, and `mount -o remount,rw` needs `CAP_SYS_ADMIN`, which
  `baseline` refuses at admission.
- **There is no uid to match.** The session runs as root and reads the tree
  whatever the application wrote it as, which is what removed the per-product
  `internalUid` and its coupling to uid conventions inside upstream images. That
  is sound **only** because nothing writes: if a product is ever given
  read-write access, the uid comes back, because uploads would land root-owned
  in a tree the application owns as another user and cannot modify.
- **`subPath` for shared volumes.** If the exposable data lives in a
  subdirectory of a volume that also holds app config or secrets (nextcloud's
  `config/config.php` has DB credentials), mount only that subdirectory.
- **Multiple volumes** become sibling directories in the session: pass several
  `mounts` entries with distinct `path`s. `sessionRoot` names the one the
  session starts in.
- **The session survives the application.** The sidecar's mount is its own and
  independent of the application container's, which is what keeps a deployment's
  data reachable while its application is crash-looping or cannot pull its
  image — the state in which retrieving it matters most.

### An application-container session root

- **The pod must set `shareProcessNamespace: true`,** and must **not** set
  `hostPID`. The shared namespace is what lets the sidecar reach the
  application; that it is the *pod's* and not the *node's* is what bounds it to
  this tenant's own containers. Without it the container still starts and
  serves — forwarding and the toolbox work — and a session that needs the
  application container says what is missing.
- **The application container gains nothing.** Everything the session root
  grants is on the sidecar.
- **The shared process namespace is symmetric.** The application container can
  see the sidecar's processes and files, which is safe only because the sidecar
  holds nothing worth seeing.
- **Debuggers are deliberately not offered.** `strace`, `gdb` and `py-spy` need
  `CAP_SYS_PTRACE`, which `baseline` refuses. Granting it means raising the
  namespace's enforcement level, which is a change to what the platform
  guarantees about tenant pods and is decided separately. Entering the
  application container needs only `CAP_SYS_CHROOT`, from the default set.
- **The database is optional, and its absence costs only the database.** A
  product with no relational storage renders no allowlist and no `PG*`
  environment; the image writes `PermitOpen none` and declines the database
  tools by name, and the shell, remote commands and file transfer are
  unchanged. The toolbox is a facility the sidecar offers, not a precondition it
  imposes.
