# Vaultwarden Chart

Self-contained Freepod chart for Vaultwarden. Renders the Deployment, Service, data PVC, admin
Secret, and per-app TLS Ingress directly — no dependencies.

- Image: `vaultwarden/server`, pinned by `image.tag` (currently `1.37.1`)
- Chart published to: `oci://ghcr.io/erikvanzijst/freepod/charts/vaultwarden`, by
  [`scripts/publish-charts.sh`](../../scripts/publish-charts.sh) — CI publishes each new
  `version` in `chart/Chart.yaml` on merge; by hand, `./scripts/publish-charts.sh vaultwarden`

Vaultwarden is a single container backed by sqlite on one PVC, so the chart is deliberately small:
one template per resource, every setting a first-class value.

## Values

See `values.yaml` for the full set. Notable entries:

| Value                | Default           | Notes                                                                                                 |
|----------------------|-------------------|-------------------------------------------------------------------------------------------------------|
| `image.tag`          | `1.37.1`          | Pinned so the app version is Caelus-owned and overridable through system values.                      |
| `signups.allowed`    | `false`           | Open registration off by default; these vaults are internet-facing.                                   |
| `signups.verify`     | `true`            | `SIGNUPS_VERIFY`. Rendering fails if set without `smtp.enabled`.                                      |
| `admin.token`        | `""`              | Blank generates a 20-character token on first install. Never shown to the user — see § Admin console. |
| `bootstrap.image`    | `curlimages/curl` | Image for the first-user invite Job.                                                                  |
| `caelus.owner.email` | injected          | Reconciler-supplied; the invitation target.                                                           |
| `storage.data.size`  | `1Gi`             | Overridden by `caelus.plan.storageSize` when the deployment has a plan.                               |
| `proxy.ipHeader`     | `X-Real-IP`       | `IP_HEADER` — see § Client IP below.                                                                  |
| `resources`          | `{}`              | Left empty deliberately: a wrong limit OOM-kills a password vault.                                    |
| `extraEnv`           | `{}`              | String-valued escape hatch for settings not modeled yet.                                              |

The `features` block carries vaultwarden's own defaults (web vault, sends, emergency access,
password hints, org creation, email change). They are surfaced so they can be tightened
deliberately rather than drifting with the image.

### Chart values vs the admin console

Most of these settings also appear as toggles in vaultwarden's own `/admin` console, under labels
that do not match the env var names — "Require email verification on signups" is `SIGNUPS_VERIFY`,
i.e. `signups.verify` here.

**Saving anything in the admin console detaches the instance from this chart.** Config edited
there is written to `/data/config.json` on the PVC, and that file overrides the environment. The
generated file includes *all* editable options, not just the one that was changed, so a single
click of Save freezes the whole configuration against every future chart value. Vaultwarden logs
which variables are shadowed at startup:

```
The following environment variables are being overridden by the config.json file.
Please use the admin panel to make changes to them:
```

Recovery is to delete the offending keys from `/data/config.json` (or reset from the admin page)
and restart. Upstream's own guidance is that config.json is *not* the recommended way to configure
an instance and that environment variables should be used — which is what this chart does.

## Bootstrapping a new instance

A fresh vaultwarden has **no accounts and seeds none**, and open registration is off, so without
help a new deployment would run perfectly and be impossible to log into.

`templates/bootstrap-job.yaml` closes that gap. After install it invites `caelus.owner.email`
through the admin API, and vaultwarden emails the owner a link where they choose their master
password. The user supplies nothing at deploy time — no admin token to invent, no window during
which a stranger could claim the first account.

The Job:

- runs as a `post-install,post-upgrade` hook, because a repeat invite returns **409 "User already
  exists"**. That idempotency means a failed first attempt self-heals on the next reconcile instead
  of needing manual repair;
- waits on `/alive` (vaultwarden's own health endpoint, which unlike `/` does not depend on the web
  vault being enabled) for `bootstrap.readyTimeoutSeconds`, kept well inside the reconciler's 300s
  helm timeout;
- authenticates by posting the plaintext token to `/admin` for a `VW_ADMIN` session cookie. A
  bearer header does not work, and the token stays plaintext even where `ADMIN_TOKEN` is stored
  Argon2-hashed, because the server verifies against the hash;
- treats a non-2xx as a **warning** if `/admin/users` shows the address anyway. That is the
  "account created but the notification email failed" case: the owner can still finish at
  `/#/register`, so a mail hiccup does not fail the release of an otherwise healthy vault;
- talks to the ClusterIP Service, never the Ingress, so blocking `/admin` at the edge would not
  affect it.

`INVITATIONS_ALLOWED` is hardwired to `true` rather than exposed as a value: an invited user can
only complete registration while it holds, so both this Job and an owner adding family members
depend on it.

## Admin console

**The admin console is platform-operated, not a tenant feature.** It is always enabled, and the
token is generated (20 characters), stored only in the `<release>-admin` Secret, and never shown to
the user. It exists so the bootstrap Job can invite the owner.

This is deliberate on both counts:

- `/admin`'s config editor writes `/data/config.json`, which overrides the environment. One click
  of Save would detach the vault from this chart permanently (see § Chart values vs the admin
  console above).
- Because the console is enabled, a token *must* be set — vaultwarden leaves `/admin`
  **unauthenticated** when the console is on without one.

The token is generated once and then stable: an explicit `admin.token` from system values wins (so
an operator can pin one), otherwise the value already in the Secret is reused, otherwise one is
generated. `lookup` returns empty under `helm template`, so dry runs render a throwaway value; real
installs generate once and reuse. A `checksum/secret` pod annotation rolls the pod when the token
changes, which a `secretKeyRef` alone would not do.

### Blocked at the ingress

`admin.blockAtIngress` (default on) renders `templates/admin-block.yaml`: a Traefik `ipAllowList`
Middleware scoped to loopback, attached to a second Ingress rule for `/admin`. No real client can
match loopback, so every public request under `/admin` gets a 403 and the console is not reachable
from the internet at all — the generated token stops being the only thing guarding it.

Traefik prioritises routers by rule length, so `PathPrefix(/admin)` wins over the `/` rule in
`ingress.yaml` with no explicit priority needed. `Prefix` covers `/admin/invite`, `/admin/users`,
`/admin/config` and the rest in one rule.

That second Ingress carries `spec.tls` but deliberately **no** cert-manager annotation:
ingress-shim names the Certificate after the secret, so a second annotated Ingress would contend
for the same Certificate resource. `ingress.yaml` owns issuance; this one only consumes the cert.

The bootstrap Job is unaffected — it reaches vaultwarden through the ClusterIP Service, which never
passes the Ingress. Operator access to `/admin` is via `kubectl port-forward`, with the token from
the `<release>-admin` Secret.

What tenants give up with `/admin`: server-level user invites, removing a user's 2FA,
deauthorizing sessions, deleting users and organizations, and diagnostics. Adding other people is
unaffected — an owner invites them from the web vault under Organization → Members → Invite User,
which is why `INVITATIONS_ALLOWED` stays on. The console has no backup function, so nothing is lost
there; users export their vault from the web vault instead.

## File access

The platform's SSH sidecar rides in the vaultwarden pod, rooted at a read-only
mount of the whole of `/data` — the sqlite vault, `attachments`, `sends` and
`rsa_key.pem`, which is exactly vaultwarden's documented backup set. The library
warns against mounting a database volume; that targets products with a separate
postgres volume, whereas here the sqlite file *is* the application data and the
only account that reaches it is the vault's owner. The release renders one SSH
object, the `<release>-ssh` Service, and holds no credential of its own. Spec:
[ssh-chart-contract](../../openspec/specs/ssh-chart-contract/spec.md).

Two details worth knowing:

- **`runAsNonRoot` moved from the pod to the vaultwarden container.** The
  sidecar runs as root — which is what reads this data whatever uid wrote it —
  so a pod-wide `runAsNonRoot` would break it. The app container keeps the full
  hardening; the pod keeps `fsGroup` and `seccompProfile`.
- **The Service selector names the app pod explicitly.** The library's default
  instance-only selector would also match the bootstrap Job's pod, which does
  not listen on 2222, so the Service would publish a dead endpoint for as long
  as that Job exists.

**Backup caveat:** `ENABLE_DB_WAL` is on, so a naive copy of `db.sqlite3` alone can be
inconsistent — the `-wal` file is part of the state. For a guaranteed-consistent personal
backup, the web vault's own export (Tools → Export vault) is the better route; file access is
for a full instance snapshot.

## Client IP

Vaultwarden reads the client IP from the header named by `IP_HEADER` and uses it for login rate
limiting and for the attempt log in the admin console. `proxy.ipHeader` defaults to `X-Real-IP`,
which is both vaultwarden's own default and the header Traefik sends — header names are
case-insensitive, so Traefik's `X-Real-Ip` matches. It is set explicitly anyway, because the right
value is a property of the edge chain rather than of this chart.

The address in that header is the real client only because of the edge configuration in
`tf/deps/system/helm/traefik/values.yaml.tftpl`: the homelab HAProxy edge forwards the client
address by PROXY protocol (`send-proxy-v2`), Traefik trusts it from the edge IP alone, and the
Service runs `externalTrafficPolicy: Local` so that source address survives kube-proxy.

That is worth knowing because the failure mode is silent. As that file's own comment notes, under
the default `Cluster` policy kube-proxy SNATs the source to the CNI gateway (`10.42.0.1`) before
Traefik sees it. Vaultwarden would keep working, but every login attempt would be attributed to
the same address and per-IP rate limiting would stop discriminating between clients.

## DOMAIN

`DOMAIN` is derived from the deployment hostname and rendered inline into the pod spec
(`_helpers.tpl` → `vaultwarden.domain`), preferring the reconciler-injected `caelus.ingress.host`
over the raw `host` value so it always matches the host the Ingress routes. Because it is part of
the pod template, a hostname change rolls the pod automatically.

Vaultwarden needs it for the admin console, email invitation links, and WebAuthn 2FA.

## Security context

The pod runs as uid/gid 1000 with `runAsNonRoot`, `seccompProfile: RuntimeDefault`,
`allowPrivilegeEscalation: false`, `capabilities: drop [ALL]`, and
`automountServiceAccountToken: false`. Vaultwarden needs no root and writes only to `/data`.

`fsGroup: 1000` owns the PVC files. The SSH sidecar reads them as root regardless, so there is
no uid for this chart to keep in step with.

`readOnlyRootFilesystem` is **not** set — vaultwarden's writable paths outside `/data` have not
been audited. That is the next hardening step, not an oversight.

## Resources

| Resource             | Name                    |
|----------------------|-------------------------|
| Deployment / Service | `<release>-vaultwarden` |
| PVC                  | `<release>-data`        |
| Secret (admin token) | `<release>-admin`       |
| Ingress              | `<release>-ingress`     |
| SSH Service          | `<release>-ssh`         |
| Job (bootstrap hook) | `<release>-bootstrap`   |

The Deployment uses `strategy: Recreate`: with a single RWO volume, a rolling update would
deadlock because the new pod cannot mount the PVC the old one still holds.

## Caelus product template

- **Chart:** `oci://ghcr.io/erikvanzijst/freepod/charts/vaultwarden`
- **Default values (system) json:** `{}` — `values.yaml` carries the defaults.
- **User values schema:** `user.schema.json` in this directory.

Both files are chart-local because vaultwarden is not in the curated catalog
(`products/catalog/`) yet. Moving it there, as immich and nextcloud have been, would fold
`chart_ref`, `system_values`, and `values_schema` into one git-managed entry.
