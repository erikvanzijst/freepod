## Why

The registry that holds tenant build output serves without authentication, and the one
place on the platform that runs untrusted tenant code — the build pod — is required to
reach it in order to push. Everything follows from that combination:

- **A build can overwrite any repository.** Another tenant's image, and more usefully
  another tenant's **layer cache**, which that tenant's next build imports and executes.
  The per-owner cache repository documented in `products/custom/builder/README.md` is
  derived from platform-supplied values precisely so two tenants never share one — but
  nothing enforces it, so the isolation argument is currently a naming convention.
- **A build can read any repository.** Tenant code controls the `Dockerfile`, so
  `FROM <registry>/<other-tenant>` is a supported operation today, and `tags/list`
  supplies the tags to pull by.
- **A build can overwrite the images every other build consumes.** The mirrored Railpack
  base images are resolved by tag, so poisoning one executes in every subsequent build.

The registry also sits on a LAN host outside Terraform, shared with unrelated systems,
addressed by a name its certificate does not cover — which is why `build.py` passes
`registry.insecure=true`, the node carries an `insecure_skip_verify` entry that no
Terraform run restores after a rebuild, and the builder reads published image configs
with certificate verification switched off. Once a bearer token is on that wire, an
unverified connection stops being untidy and becomes a way to harvest one.

Finally, both environments share one registry, so dev user 5 and prod user 5 address the
same repository — a collision `CAELUS_CACHE_SCOPE` exists only to paper over.

## What Changes

- **Each environment gets its own registry**, deployed by `tf/app` into a dedicated
  namespace (`caelus-registry` / `caelus-registry-dev`), addressed as `cr.freepod.eu`
  and `cr.dev.freepod.eu`. No Ingress: a pinned ClusterIP from the service CIDR, with a
  public DNS record pointing at that non-routable address, so the registry is reachable
  from the node and from build pods, and from nowhere else.
- **TLS is real.** cert-manager issues each name a certificate over DNS-01 and the
  registry terminates TLS itself. **BREAKING** for the node: the `registries.yaml`
  insecure entry is removed, which retires one of the two node-level prerequisites a
  rebuilt node currently needs.
- **Authentication is mandatory for every operation.** The registry runs with token
  authentication only, trusting a JWKS of platform keys. No anonymous pull, no anonymous
  push, and `_catalog` is never authorized.
- **A build receives a short-lived capability, not a credential.** The build worker mints
  a signed token naming exactly six repositories — push+pull on the owner's image and
  cache repositories, pull on the mirrored base images — which BuildKit consumes
  verbatim. The build pod contacts no token endpoint and holds nothing that outlives its
  build.
- **Deployments pull with a per-owner credential.** The reconciler publishes a
  `dockerconfigjson` Secret into each deployment namespace whose password is derived by
  HMAC from a platform key, so the issuer verifies it by recomputation and keeps no user
  table. A leaked pull credential reads one owner's images on a registry with no route
  from the internet.
- **The token endpoint is a route on the existing API**, not a new deployment — it mints
  pull scopes only. Push capability exists solely as a signature produced in-process by
  the build worker.
- **Repository layout becomes `u/{uid}` and `cache/{uid}`**, with the mirrored base
  images at their upstream paths because BuildKit asks a mirror for the same path.
- **`CAELUS_CACHE_SCOPE` is retired.** Separate registries make the environment
  discriminator redundant.
- **The registry host becomes a reconciler-injected system value.** One chart serves both
  environments and the host now differs between them, so it can no longer be a chart
  default.
- **`registry.home` stops being used by the platform** once the 17 live images are copied
  and every `custom` deployment is moved to the template carrying the new host.

Deferred deliberately: pull-through caches for ghcr.io and Docker Hub, and tag retention.
`delete` is enabled and a garbage collection job runs, but what bounds an owner's
accumulated builds is left to a follow-up now that the node has headroom for it.

## Capabilities

### New Capabilities
- `tenant-image-registry`: the registry as a platform component — one per environment,
  cluster-internal, how it is addressed and trusted, what it stores, how storage is
  reclaimed, and what it means for the previous registry to be retired.
- `registry-authorization`: who may read and write what, and how that is proven. Covers
  the mandatory-authentication rule, the shape and bounds of a build's capability, the
  per-owner pull credential and its derivation, and the token endpoint's contract.
- `registry-chart-contract`: what a product chart is handed so it can run a tenant image
  — the registry host and the pull secret name as system values — and why neither may
  come from a tenant.

### Modified Capabilities
- `build-execution`: the credential requirement. The build container now holds a
  registry capability, which the existing requirement neither anticipates nor bounds; it
  is restated to say what the container may hold, scoped to what, and for how long.

## Impact

- **Terraform** (`tf/app`): new registry module (namespace, Deployment, PVC, Service with
  pinned ClusterIP, Certificate, config, JWKS ConfigMap, restart CronJob, GC CronJob),
  two new secrets threaded to the API, reconcile worker and build worker, and an egress
  change in `caelus/builds.tf`.
- **API** (`api/app/`): the token endpoint route; `services/build_jobs.py` token minting;
  `services/reconcile.py` pull-secret publication and the registry system override;
  `config.py` settings; new signing and HMAC key handling.
- **Builder image** (`products/custom/builder/`): docker config with the minted token,
  removal of every insecure flag, authenticated and verified image-config read, cache ref
  without the environment scope; new `VERSION`.
- **Chart** (`products/custom/chart/`): `imagePullSecrets`, registry host as a system
  value, values schema; new chart version, published to ghcr.io.
- **Catalog and deployments**: a new `custom` template version, and every `custom`
  deployment moved to it.
- **Node**: the `registries.yaml` insecure entry is deleted.
- **Docs**: `api/README.md` § Builds, the builder README's cache and mirror sections,
  `tf/README.md`, `tf/app/README.md`, and an AGENTS.md entry.
