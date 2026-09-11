## Context

See [proposal.md](./proposal.md) § Why. The constraints that shaped the design, and the
upstream behavior it depends on — all of it read from source rather than documentation
prose, because several widely repeated claims about registry authentication are wrong:

- **A registry accepts exactly one authentication provider.** `configuration.go`'s
  `Auth.UnmarshalYAML` rejects a map with more than one key: *"must provide exactly one
  type"*. `htpasswd` and `token` cannot coexist, so a static operator password and minted
  capabilities cannot both be checked by the registry. Whichever credentials exist have to
  meet somewhere else.
- **Authorization scopes are matched exactly.** `accesscontroller.go` builds an
  `accessSet map[auth.Resource]actionSet` and authorizes by map lookup on `{type, name}`.
  There are no wildcards and no prefix semantics: `u/5` authorizes `u/5` and nothing else.
- **A token may be trusted by key id against a JWKS file**, not only by an X.509 chain
  (`token.go`'s `VerifySigningKey` falls through to `TrustedKeys[header.KeyID]`; the
  `jwks` option exists in distribution v3.0.0 and **not** in 2.8.3). No certificate
  authority is needed.
- **A build daemon consumes a pre-minted bearer token verbatim.** BuildKit's
  `authprovider.go` short-circuits on `ac.RegistryToken`, so a build never performs a
  credential exchange. The same provider serves the image export and the cache
  import/export, so one entry covers all three.
- **The node's container runtime cannot carry a bearer token.** Kubernetes'
  `DockerConfigEntry` (`pkg/credentialprovider/config.go`) holds only username, password,
  email and the encoded pair — no token field. containerd therefore always performs the
  challenge/exchange (`authorizer.go`'s `doBearerAuth`), attempting a form-encoded
  exchange first and falling back to a header-carried one on 400, 401, 404, or 405.
- **A pull-through cache is structurally read-only** — every write path in
  `registry/proxy/` returns `distribution.ErrUnsupported` — and mirrors only one upstream
  per instance, at a hostname with no path prefix. Relevant to what is deferred, not to
  what is built here.

Measured facts about the environment it lands in:

- The node has **67 GiB free of 105 GiB**, after 50 GiB was added. Existing tenant content
  on the old registry is **5.68 GiB across 96 build tags**, of which **17 images are
  referenced by a live deployment**.
- The service CIDR is `10.43.0.0/16`. Of 99 services holding a ClusterIP, only
  `10.43.0.1` and `10.43.0.10` sit below `10.43.1.0`: dynamic allocation lands in the
  upper band, and the low band is reserved for static assignment.
- A pod on the node's host network reaches a ClusterIP (probed against the Garage service,
  which answered), which is the path the kubelet's pulls take.
- `letsencrypt-dns` is an established ClusterIssuer, already used for per-account
  certificates, so DNS-01 needs no new plumbing.
- `_build_ssh_overrides` in `services/reconcile.py` already injects a per-environment
  setting into every chart as a system value — the precedent D13 follows.

## Goals / Non-Goals

**Goals:**

- One tenant cannot read, write, or poison another's images or layer cache, enforced by
  the registry rather than by naming convention.
- Nothing the build pod holds outlives the build or reaches beyond it.
- No credential and no trust configuration on the node.
- The whole registry is Terraform-owned, per environment, and rebuildable.

**Non-Goals:**

- Pull-through caches for ghcr.io and Docker Hub. Deferred; the existing mirror of the
  Railpack images moves to the new registry unchanged (D17).
- Tag retention. Storage is reclaimable and collected (D16), but nothing yet bounds an
  owner's accumulated builds.
- Proving an image was produced by a build. A tenant with a build capability can push a
  hand-made image into their own repository; they can equally build one, so this buys
  nothing today. If it ever matters, the build pushes to a staging repository and the
  worker promotes it.
- Replacing the platform's use of ghcr.io for charts and platform images.
- Multi-replica or highly-available registry. One replica, RWO storage, single node.

## Decisions

### D1: In the cluster, per environment, under `tf/app`

Each environment's registry is part of that environment's application infrastructure, not
a shared singleton in `tf/deps`. That is what makes D12's repository layout possible: with
one registry per environment there is no identifier collision between environments, so
nothing needs an environment discriminator.

### D2: A pinned ClusterIP in public DNS, and no Ingress

`cr.freepod.eu` and `cr.dev.freepod.eu` resolve to pinned ClusterIPs (`10.43.0.20` and
`10.43.0.21`, from the statically-reserved low band). Publishing a DNS record for a
non-routable address is deliberate: the name has to resolve for the node's container
runtime, and resolving is not reaching.

*Alternative considered:* a `cluster.local` name. Rejected on a harder ground than the
missing certificate — containerd resolves image hostnames through the **node's** resolver,
which knows nothing of cluster DNS, so the one client that matters most could not resolve
it at all.

*Alternative considered:* exposing it through the shared edge. Rejected — it would put the
registry on the internet, which is the reachability bound this design leans on, and would
couple a per-environment component to a cluster singleton.

### D3: The registry terminates its own TLS, and a CronJob restarts it weekly

cert-manager issues each name a certificate over DNS-01 and the registry serves it
directly. No ingress object, no Traefik entrypoint, nothing shared.

`registry:3` reads its certificate at startup, so renewal needs a restart. A weekly
CronJob with permission to restart that one Deployment covers it with a wide margin:
cert-manager renews at a third of remaining lifetime — about 30 days before expiry on a
90-day certificate — so the worst case is a pod serving a certificate with three weeks
left.

### D4: A dedicated namespace per environment

`caelus-registry` and `caelus-registry-dev`, rather than the environment's `caelus`
namespace. The build namespace's policy states that a build pod must never reach the
platform's namespace; putting the registry there would turn that into "except for one
pod", which is harder to audit than one more namespace.

### D5: Token authentication only, with credentials checked outside the registry

Since only one provider can be configured, the registry runs `token` and every credential
that is not already a token is checked by the platform's own endpoint, which then mints
one. This is what lets a static credential and a minted capability coexist at all.

### D6: Trust by key id against a JWKS, not a certificate chain

The registry is configured with `jwks` and trusts keys by `kid`. No CA, no certificate
rotation, and the key set admits several keys at once, so rotation is: publish the new
public key, switch signers, drop the old.

This requires distribution v3 — `jwks` does not exist in 2.8.3 — which `registry:3`
provides.

### D7: The build's capability is pre-minted and handed to the pod

`build_jobs.py` holds the signing key and mints the token itself; the pod receives it in
its Docker configuration and BuildKit uses it verbatim. The build pod never contacts the
token endpoint, so the endpoint needs no build-facing authentication, and there is no
credential in the pod that could be exchanged for anything else.

For build `7f3a9c…` owned by user 5 in dev:

```json
{ "typ": "JWT", "alg": "ES256", "kid": "dev-1" }
```
```json
{
  "iss": "caelus-build-worker",
  "sub": "build:7f3a9c2e-...",
  "aud": "cr.dev.freepod.eu",
  "iat": 1757592000, "nbf": 1757591940, "exp": 1757596200,
  "jti": "9d1c...",
  "access": [
    { "type": "repository", "name": "u/5",     "actions": ["pull", "push"] },
    { "type": "repository", "name": "cache/5", "actions": ["pull", "push"] },
    { "type": "repository", "name": "railwayapp/railpack-frontend", "actions": ["pull"] },
    { "type": "repository", "name": "railwayapp/railpack-builder",  "actions": ["pull"] },
    { "type": "repository", "name": "railwayapp/railpack-runtime",  "actions": ["pull"] },
    { "type": "repository", "name": "docker/dockerfile",            "actions": ["pull"] }
  ]
}
```

`Verify` checks `iss` against the configured issuer, `aud` against the configured service,
and `exp`/`nbf` with 60s leeway; `sub`, `iat` and `jti` are unverified and exist for the
audit trail. `exp` is the build deadline plus margin — about 70 minutes — so a build that
runs to its deadline can still push. `pull` accompanies `push` on both writable
repositories because a cache hit is mounted across repositories at push time, and that
mount reads the source.

Since the mirrored base images live in the same registry (D17), the pod's Docker
configuration needs exactly one entry, covering the push, the cache, and the mirror pulls.

### D8: Six exact repository names, never a pattern

Scopes match exactly, so the capability enumerates. This is a constraint turned into a
property: there is no expression in the token that could match more than intended, and the
list is short enough to assert in a test. A design keyed on a per-build random prefix —
`builds/{id}/*` — was considered early and is simply not expressible.

### D9: No anonymous access, including reads

An earlier draft allowed anonymous pull on the grounds that tenant application pods cannot
route to the registry. That reasoning was wrong: build pods **must** reach the registry in
order to push, and build pods execute tenant-supplied code. With anonymous read, a
project's `Dockerfile` naming `FROM cr.freepod.eu/u/7` would be served another tenant's
image, and `tags/list` — also a read — would supply the tags to name.

So reads authenticate too. The cost is the per-owner pull credential of D11; the
alternative was a cross-tenant read channel open to anyone who can write a Dockerfile.

### D10: The token endpoint is a route on the API, not a sidecar

`/api/registry/token` on the existing API deployment. A separate service would cost a
Python runtime's memory on a node where that is the scarce resource, and the endpoint is
one route.

The consequence is that it is internet-facing, which is acceptable because of D3's
companion rule in `registry-authorization`: **the endpoint mints read access only**. Write
capability exists solely as a signature produced in-process by the build worker. The worst
case for the public route is read access to one owner's images on a registry with no route
from the internet.

*Alternative considered:* blocking the route at the ingress and having containerd reach
the API's Service directly. Rejected because it reintroduces exactly what this change
removes — an internal name needs a certificate the node trusts and a resolver entry,
which means a `registries.yaml` block and a node-local dependency outside Terraform.

*Honest limit:* the registry cannot enforce the read-only property. Any key in its JWKS
may sign any access claim, so the API's key could technically mint write. Separate keys
give attribution by `kid`, not enforcement. Someone who can make the API sign arbitrary
tokens already holds its database credentials and cluster RBAC.

### D11: Per-owner pull credentials, derived rather than stored

The reconciler publishes a `dockerconfigjson` Secret into each deployment namespace,
before Helm runs, alongside the object-storage and database Secrets it already writes:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: <release>-registry-pull
  namespace: <deployment namespace>
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: <base64 of the document below>
```
```json
{ "auths": { "cr.freepod.eu": {
    "username": "pull-5",
    "password": "<HMAC(key, 'registry-pull:v1:5')>",
    "auth": "<base64 of 'pull-5:<password>'>" } } }
```

Deriving the password means the endpoint verifies by recomputation: no table of issued
credentials, nothing to reconcile, nothing to leak in bulk. The `v1` marker is the
rotation handle — change it and every Secret is rewritten on the next reconciliation pass.
`auth` is what the kubelet actually decodes; the other two fields are what every registry
client writes.

*Alternative considered:* one cluster-wide pull identity in the node's `registries.yaml`.
Rejected twice over: it is node configuration no Terraform run restores after a rebuild,
and a single `pull` identity for every repository re-opens the cross-tenant read that D9
closes, this time for anything that can read the node's filesystem.

### D12: `u/{uid}` for images, `cache/{uid}` for caches, upstream paths for mirrors

The mirror paths are not a free choice: BuildKit asks a mirror for the same repository
path it would have asked upstream for, so the Railpack images sit at `railwayapp/…` at the
root. Given that, prefixing tenant content keeps the root legible and the authorization
policy a flat list.

`CAELUS_CACHE_SCOPE` is retired by D1. The image reference a build reports —
`{uid}@{digest}`, with the host stripped — does not change, because the prefix lives in
the registry value the chart is handed (`cr.dev.freepod.eu/u`), not in the tenant's half.

### D13: The registry host is injected by the reconciler, not defaulted in the chart

One chart serves both environments and the host now differs between them, so a
`values.yaml` default cannot be right for both. `_build_ssh_overrides` already does exactly
this for the platform SSH key: read a per-environment setting, inject it as a system
value. The registry host and the pull Secret's name follow it.

### D14: Two keys per environment, generated by a CLI command

A signing keypair (EC P-256 — smallest tokens) and an HMAC key, both per environment
because both are environment-scoped secrets:

| Value | Held by |
|---|---|
| signing private key | `caelus-api` (mints pull tokens), `caelus-build-worker` (mints build capabilities) |
| signing public key, as JWKS | the registry, as a ConfigMap |
| pull HMAC key | `caelus-api` (verifies), `caelus-worker` (derives when publishing Secrets) |

They live in `secrets.auto.tfvars` keyed by workspace, looked up the way
`var_encryption_keys` already is, and reach their pods as Secrets consumed by
`env_from`, following `kubernetes_secret.var_keys`. They are kept as **two separate
Secrets** so neither worker holds a key it has no use for: the build worker never needs
the HMAC key, and the reconcile worker never needs the signing key.

`jwks` is a file path, so the public half must arrive as a ConfigMap in JWK form, and
converting PEM to JWK in HCL is unpleasant. A `caelus registry-keygen` command prints both
halves — private PEM for tfvars, JWKS JSON for the ConfigMap variable — generated once per
environment and documented, the way `sshpiper_upstream_private_keys` already is.

### D15: Copy the 17 referenced images, not the other 79

`crane copy` preserves manifest digests across repositories, so a copied image keeps the
digest every stored reference names and nothing has to be rewritten. Unreferenced images
are left behind: a user redeploying a long-dead build would get a pull failure, which is a
better trade than carrying 79 tags forward on the assumption someone might.

Caches start cold. The builder already handles an absent cache — BuildKit warns and
proceeds — so nothing needs pre-creating.

### D16: Collection now, retention later

`delete` is enabled and a CronJob runs garbage collection, which reclaims what nothing
references. What is **not** built here is a retention rule — keeping the current release's
image plus the last N builds per owner — because that requires knowing which images are
live, which is database knowledge. Its natural home is `caelus db-worker`, which already
purges deleted deployments' databases and reclaims orphaned cluster objects.

With 67 GiB free against 5.68 GiB of accumulated content, deferring is affordable. It is
still the thing that will eventually matter, since `local-path` enforces no quota and a
PVC size bounds nothing.

### D17: The Railpack mirror moves to the new registry

`scripts/mirror-railpack-images.sh` is repointed at the new registry rather than retired.
Under the old registry this was a poisoning channel — any build could overwrite a base
image every other build executes. Under D8 no tenant capability carries write on those
repositories, so the mirror becomes safe by construction, and the ~26 seconds it saves on
every build survives the migration.

Pull-through caches would subsume this and remove the version-pin chasing with it, but
they are a separate change: each upstream needs its own instance at its own hostname.

### D18: No NetworkPolicy in the registry namespace

The registry namespace gets no ingress policy, and the registry makes no outbound
connections worth restricting.

Reachability stopped being the boundary when D9 made authentication mandatory: every
request needs a token, so the question a policy would answer — who may *attempt* a
connection — no longer decides who may do anything. And the principals that can route to
the ClusterIP are already bounded from the other end. Tenant application pods are blocked
by their own namespace's baseline egress rule, which excludes every private range; build
pods are bounded by the builds namespace's egress rule, which is the load-bearing one and
is unaffected by anything here; everything else that could reach it is platform-owned and
still has to authenticate.

What a policy would add is defense in depth against pre-authentication surface in the
registry process. What it would cost is the failure mode described under Risks: the
kubelet pulls from the node's host network, so the natural `podSelector` rule silently
blocks every image pull. Given mandatory authentication, that is a poor trade.

## Risks / Trade-offs

- **Nothing restricts who may attempt a connection to the registry** (D18) → accepted:
  every attempt still has to authenticate, and the two principals that can route to it at
  all are the node and build pods. If a pre-authentication weakness in the registry ever
  makes reachability worth restricting again, note that the kubelet's pulls come from the
  node's host network rather than from a pod, so a `podSelector` rule will not match them
  and a policy written the obvious way blocks every image pull — failing in a way that
  reads like a DNS or certificate problem.
- **While the API is down, new tenant pods cannot pull.** Running pods and node-cached
  images are unaffected → accepted: on a single-node platform an API outage is already an
  outage, and the alternative costs a separate always-on service.
- **A silently failing restart CronJob surfaces as an expired certificate weeks later** →
  the job is small enough to assert in the rollout, and the 30-day renewal margin means
  several missed runs are survivable rather than immediately fatal.
- **The registry is a single replica on RWO storage**, so a rollout is a brief outage in
  which pulls fail → the kubelet retries, and builds fail cleanly rather than corrupting
  anything. Not worth an HA design on one node.
- **A capability that expires mid-push fails a long build near its deadline** → `exp` is
  the deadline plus margin, so only a build that overruns its own deadline can hit this,
  and that build is being killed anyway.
- **Storage growth is unbounded until retention lands** (D16) → collection reclaims
  unreferenced content, the node has headroom, and the follow-up is scoped.
- **The migration has an ordering constraint**: the chart and template move must land
  after the images are copied, or a reconciled deployment resolves an image that is not
  there yet → the plan below orders it, and per-deployment rollback stays available until
  the old registry is retired.

## Migration Plan

1. Stand up both registries, the token endpoint, and the keys. Nothing consumes them yet.
2. Verify by hand: an authenticated pull works, an unauthenticated one is refused, the
   catalog is refused, and a pull from the node succeeds.
3. Mirror the Railpack base images into both registries.
4. Ship the builder change and the build-worker minting; builds now push to the new
   registry while deployments still pull from the old one.
5. Copy the 17 referenced images, preserving digests.
6. Ship the reconciler's pull-Secret publication and the chart change; roll out a new
   `custom` chart version and template.
7. Move `custom` deployments to the new template, one first, then the rest.
8. Audit: no template and no live deployment resolves a tenant image from the old
   registry.
9. Remove the node's `registries.yaml` entry; confirm pulls still work after a kubelet
   restart.
10. Retire the old registry's repositories.

**Rollback:** through step 7, a deployment is pointed back at the previous template version
and pulls from the old registry, which is still serving. After step 10 the rollback is
restoring images to the old registry, which is why the audit gates it.

## Open Questions

- The exact pinned ClusterIPs, subject to confirming they are unallocated at apply time.
