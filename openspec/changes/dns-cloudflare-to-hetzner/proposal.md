## Why

`freepod.eu`'s authoritative DNS is on Cloudflare's free plan, which caps a zone created after
1 September 2024 at 200 records. Raising that cap is an Enterprise conversation; there is no
tier between Free and Pro ($20/mo), and no add-on that lifts it.

That cap is survivable today, because the zone holds a handful of platform records. It stops
being survivable the moment the platform allocates DNS records per user account — which the
per-user subdomain architecture requires, because a wildcard record under each user's label is
what keeps their applications resolving while an ACME challenge is in flight beneath it. At one
record per account, a 200-record zone is a 200-customer platform.

Hetzner documents 500 records per zone and marks the limit as increasable on justified demand,
publishes a first-party cert-manager webhook and Terraform provider, and is EU-based, which the
platform's positioning is not incidental to.

This change moves the zone. It does not create any per-user record: that belongs to the
per-user TLS work, which this unblocks rather than implements.

## What Changes

- **`freepod.eu`'s authoritative nameservers become Hetzner's.** The domain's registration does
  not move; only the NS delegation changes.
- **The zone is declared in Terraform** using the `hcloud` provider's zone and RRset resources,
  rather than existing only as hand-entered records in a vendor dashboard. The record set
  becomes reviewable in a diff before it is ever authoritative, which is also what makes the
  parity check against the Cloudflare export a code review rather than a screenshot comparison.
- **cert-manager's DNS-01 solver changes from Cloudflare to the Hetzner webhook.** Both the
  production and staging `ClusterIssuer`s, plus the webhook's own Helm release in the
  `cert-manager` namespace. The `Certificate` resources are untouched.
- **DNSSEC is deliberately disabled before the delegation changes**, and its DS record removed
  at the registry with its TTL waited out. A signed zone whose delegation moves without that
  step fails closed at every validating resolver — which is most of them — and the failure is
  not partial.
- **The Cloudflare credential is removed** from `tf/deps`, including the vestigial
  `cloudflare_email` variable the solver never used.
- **The Cloudflare zone is retained, unmodified, well past cutover**, as the rollback path.

## Capabilities

### New Capabilities

- `platform-dns`: where `freepod.eu`'s authoritative DNS is served, what the zone must contain
  for the platform to function, how records are managed, and the constraints that keep
  certificate issuance and mail working.

### Modified Capabilities

- `freepod-cert-manager`: the DNS-01 `ClusterIssuer` is solved by the Hetzner webhook rather
  than the built-in Cloudflare solver, and holds a Hetzner token rather than a Cloudflare one.

## Impact

- `tf/deps/certmanager/issuers.tf`: the solver block on both DNS-01 issuers, and the API token
  Secret.
- `tf/deps/certmanager/`: a new Helm release for `hcloud/cert-manager-webhook-hetzner`.
- `tf/deps/variables.tf`, `tf/deps/main.tf`, `tf/deps/certmanager/variables.tf`: the Cloudflare
  token and email variables are replaced by a Hetzner token.
- `tf/deps/providers.tf`: the `hcloud` provider is added.
- A new Terraform module holding the zone and its records.
- Everything the platform serves depends on this zone: `freepod.eu`, `keycloak.freepod.eu`,
  Grafana, every deployment hostname, and the SSH edge, which clients reach by name. A failed
  cutover is a total outage, not a degraded one.
- Not affected: the domain's registrar, the `Certificate` resources and their secrets, Traefik,
  and every application. Nothing outside `tf/deps` changes.
