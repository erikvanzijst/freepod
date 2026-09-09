## Why

Freepod is moving to per-user hostname namespaces, where an account's applications are
addressed under its own label — `photos.alice.freepod.eu`. TLS wildcards match exactly one
label, so the `*.freepod.eu` certificate that serves every application today does not cover
those names, and nothing in the platform can issue or serve what would.

This change builds that machinery and nothing else. Deployments keep their flat hostnames
and keep being served by the default wildcard, so nothing user-visible changes. What lands
is the per-account DNS record, the per-account certificate, and the mechanism that puts it
where the ingress controller will find it — verifiable on its own, before any hostname moves.

## What Changes

- **A wildcard DNS record per account**, `*.<subdomain>.freepod.eu`, created through the DNS
  provider's API when the account first deploys.

  This record must not be removed as redundant, even though on the current provider it is.
  Issuing the certificate writes an ACME challenge record at
  `_acme-challenge.<subdomain>.freepod.eu`, which makes `<subdomain>.freepod.eu` exist as an
  empty non-terminal; RFC 4592 then stops `*.freepod.eu` answering for anything beneath it, and
  only the account's own wildcard does. Cloudflare does not implement that rule (measured
  2026-09-08), so the hazard is latent rather than absent — it arrives with any conformant
  provider, for every account that does not already hold a record.

- **The provider is reached through a thin adapter**, so that changing DNS provider is a new
  implementation rather than a change to the reconciler.

- **A cert-manager `Certificate` per account**, covering `*.<subdomain>.freepod.eu` and
  `<subdomain>.freepod.eu`, issued over DNS-01, in a new platform-owned namespace. One
  certificate per account rather than per deployment: certificate count then tracks signups,
  which cannot be churned, rather than deployments, which can.

- **A new `caelus-tls` namespace** holding that certificate, every other account's, and the
  platform wildcard.

- **`TLSStore/default` moves out of the Traefik Helm release** into that namespace and becomes
  platform-owned. Its `certificates` list is what makes an account's certificate available to
  routes in namespaces that know nothing about it — the ingress controller matches by SNI in
  memory, downstream of namespaces, so nothing has to be copied anywhere.

- **The list is derived from the secrets that exist**, not from the database, and written with
  a compare-and-swap precondition so that concurrent workers cannot lose each other's entries.

- **The reconcile waits for the certificate, and fails without one.** Issuance usually finishes
  before the Helm install does; when it does not, the deployment stays provisioning and its job
  is deferred rather than completing — a reconcile that completes early writes a store that omits
  the new certificate and has no reason to write again. The wait is bounded, and exhausting it
  fails the deployment. Nothing is addressed under account names yet, so completing anyway was
  available and was rejected: it is a leniency someone would have to find and reverse when
  hostnames move.

## Capabilities

### New Capabilities

- `account-dns-record`: the wildcard DNS record an account gets, why it is mandatory rather
  than convenient, and how the platform reaches its DNS provider.
- `account-tls-certificate`: the certificate an account holds — what it covers, when it is
  requested, where it lives, and that nothing ever deletes it.
- `platform-tls-store`: the certificate store the ingress controller reads — who owns which
  field of it, how its membership is derived, and how it is written safely by concurrent
  workers.

### Modified Capabilities

- `freepod-tls-termination`: the default certificate store stops being a value of the Traefik
  Helm release and becomes a platform-owned object in its own namespace, and gains a third
  source of certificates alongside the default and per-route ones.

## Impact

- A new Terraform module for the `caelus-tls` namespace and the `TLSStore/default` object;
  `tlsStore` is removed from the Traefik chart's values.
- The platform wildcard `Certificate` moves from `kube-system` to `caelus-tls`, because
  `defaultCertificate` resolves its secret in the store's own namespace.
- `api/app/provisioner.py`: server-side apply with a field manager, and methods to ensure an
  account certificate, list certificate secrets, and reconcile the store.
- `api/app/services/dns.py` (new): the provider adapter, alongside the object-storage and
  payment adapters it is modeled on. The Cloudflare implementation uses the official `cloudflare`
  SDK, a new dependency in `api/pyproject.toml` whose transitive requirements are already there.
- `api/app/models/core.py` and a migration: the nullable `subdomain` column on `UserORM`, taken
  from `account-subdomain-claim` section 1 because nothing else here has a name to issue for.
  That change's own sections 2 onward are untouched.
- `api/app/services/reconcile.py`: the per-account provisioning step, before the Helm release.
- `api/app/config.py`: the TLS namespace, the store name, the DNS provider credential and
  zone, and the record target.
- Not affected: the product charts, the tenant namespaces, custom-domain certificates, and
  `app-tls-injection` — deployments continue to render a plain Ingress and be served by the
  default wildcard.
- `tf/app/caelus`: a `caelus-dns` Secret for the provider token and the zone id in the API
  ConfigMap, fed by `cloudflare_api_dns_token` and `cloudflare_zone_id` in
  `tf/app/secrets.auto.tfvars`. They live in `tf/app` rather than `tf/deps` because the root
  module that renders the reconciler's pod is the one that can reach them — the two roots share
  no state.
- Depends on the `subdomain` column from `account-subdomain-claim` section 1, which this change
  implements; nothing else from that change is required, and an account holding no subdomain
  fails its reconcile rather than being handled leniently.
- The `caelus-tls` namespace, the store and the platform wildcard's move are singletons in a
  cluster that serves both environments, so those steps are not environment-scoped even though
  the rest of this change is rolled out on dev first.
