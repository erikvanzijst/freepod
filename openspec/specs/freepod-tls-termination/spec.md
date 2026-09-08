# freepod-tls-termination Specification

## Purpose
Terminate TLS on freepod Traefik itself — default wildcard cert store, PROXY-protocol client-IP preservation, and an ACME-safe HTTP→HTTPS redirect.

## Requirements
### Requirement: Freepod Traefik terminates TLS using the wildcard as the default certificate
Freepod Traefik SHALL terminate TLS itself (rather than receiving plaintext HTTP from upstream),
and SHALL serve the `*.freepod.eu` wildcard secret as the **default certificate** of its
certificate store. `*.freepod.eu` application Ingresses SHALL therefore require no per-app TLS
secret.

The store SHALL be a platform-owned `TLSStore` named `default`, living in the namespace that
holds the certificate secrets it names, and SHALL NOT be rendered by the Traefik Helm release —
a store whose membership changes with the fleet cannot be owned by a chart that resets it on
upgrade. The default certificate's secret SHALL reside in that same namespace, because a store's
certificate references carry no namespace and resolve in its own.

Traefik SHALL populate its running certificate store from three sources: the store's default
certificate, the store's list of additional certificates, and the TLS secret of any Ingress or
IngressRoute that names one. Selection among them is by server name at handshake time, so a
certificate from any of the three is served to a matching connection regardless of which
namespace the route handling it was defined in.

#### Scenario: Wildcard app served by the default certificate
- **WHEN** a TLS connection arrives at freepod Traefik with SNI `<app>.freepod.eu` and the app's
  Ingress has no explicit `tls:` secret
- **THEN** Traefik serves the default certificate and routes to the app
- **AND** no per-namespace certificate or secret reflection is needed for `*.freepod.eu` apps

#### Scenario: Custom-domain app served by its own certificate
- **WHEN** a TLS connection arrives with SNI for a custom domain whose Ingress references a
  per-app `tls:` secret
- **THEN** Traefik serves that per-app certificate (issued by the HTTP-01 issuer) for the
  custom domain

#### Scenario: A listed certificate is served without a route referencing it
- **WHEN** a TLS connection arrives with an SNI matching a certificate listed in the store, and
  the route that would handle the request names no TLS secret
- **THEN** Traefik serves the listed certificate rather than the default one

#### Scenario: The store survives a Traefik release upgrade
- **WHEN** the Traefik Helm release is upgraded
- **THEN** the store and every certificate it lists are unchanged, because the release does not
  render it

### Requirement: Client IP is preserved via PROXY protocol from the HAProxy edge
Freepod Traefik's `web` and `websecure` entrypoints SHALL trust **PROXY protocol** only from the
HAProxy edge IP (`proxyProtocol.trustedIPs`), and the blanket
`forwardedheaders.insecure=true` trust SHALL be removed. The Traefik Service SHALL set
`externalTrafficPolicy: Local` so klipper/kube-proxy does not SNAT the source to the node CNI
gateway before Traefik sees it (otherwise the source is not the trusted edge IP and the PROXY
header is ignored). The real client IP carried by the edge's `send-proxy-v2` SHALL be surfaced to
applications via `X-Forwarded-For`.

#### Scenario: App sees the real client IP
- **WHEN** an external client connects through the HAProxy edge and Traefik terminates TLS
- **THEN** Traefik reads the client IP from the PROXY-protocol header sent by the edge
- **AND** the application receives that client IP in `X-Forwarded-For`, not the edge or CNI-gateway IP

#### Scenario: Forwarded headers are not blanket-trusted
- **WHEN** freepod Traefik configuration is inspected
- **THEN** `--entrypoints.websecure.forwardedheaders.insecure=true` is not present
- **AND** PROXY-protocol trust is scoped to the HAProxy edge IP

### Requirement: No entrypoint-level redirect (it deadlocks HTTP-01)
Freepod Traefik SHALL NOT use an entrypoint-level HTTP→HTTPS redirect
(`entrypoints.web.http.redirections`). That redirect is applied *before* router matching, so it
shadows cert-manager's HTTP-01 solver Ingress and deadlocks custom-domain issuance (and leaks the
internal `:8443` port). The HTTP-01 solver SHALL therefore be reachable as plain HTTP on `:80`.
Any HTTP→HTTPS redirect SHALL instead be a router-level redirect (a low-priority web-only
IngressRoute + `redirectScheme` Middleware) that cert-manager's longer solver rule out-ranks.

#### Scenario: ACME challenge is served on plain :80
- **WHEN** a request for `http://<custom-domain>/.well-known/acme-challenge/<token>` arrives on :80
- **THEN** the cert-manager solver serves it as plain HTTP (no redirect to HTTPS)
- **AND** the certificate can be issued even though no HTTPS certificate yet exists

#### Scenario: A router-level redirect does not shadow the solver
- **WHEN** an HTTP→HTTPS redirect is configured as a low-priority web-only IngressRoute
- **THEN** non-ACME `:80` traffic is redirected to HTTPS (to `https://host`, no internal port)
- **AND** the exact ACME challenge path still reaches the solver (its rule out-ranks the redirect)

### Requirement: Websecure is the default entrypoint for unannotated routers
Freepod Traefik SHALL mark `websecure` as the default entrypoint and `web` as non-default
(`ports.websecure.asDefault: true`, `ports.web.asDefault: false`), so any Ingress or router without
an explicit `traefik.ingress.kubernetes.io/router.entrypoints` annotation binds `websecure` (`:443`)
only. Application Ingresses SHALL therefore be HTTPS-only without any per-app entrypoint annotation,
and their plain-HTTP `:80` traffic falls through to the cluster-wide redirect. Routers that must
serve `:80` (the catch-all redirect IngressRoute, the OAuth2 endpoints, the webhook receiver) SHALL
continue to declare their entrypoints explicitly and are unaffected by the default.

#### Scenario: An app Ingress without an entrypoint annotation is HTTPS-only
- **WHEN** an Ingress with no `router.entrypoints` annotation is reconciled on freepod Traefik
- **THEN** it binds the `websecure` entrypoint only
- **AND** its `:80` traffic is handled by the cluster-wide HTTP→HTTPS redirect

#### Scenario: Explicitly-annotated routers still bind web
- **WHEN** a router declares `web` explicitly (e.g. the redirect IngressRoute or the OAuth2 endpoints)
- **THEN** it continues to bind `:80` regardless of the `websecure` default

### Requirement: The HTTP-01 solver Ingress is pinned to the web entrypoint
The cert-manager HTTP-01 solver Ingress SHALL be pinned to the `web` entrypoint via the issuer
solver's `ingressTemplate` annotation `traefik.ingress.kubernetes.io/router.entrypoints: web`, on
both the production and staging HTTP-01 ClusterIssuers. This is required because `web` is no longer
a default entrypoint, and the solver Ingress otherwise carries no entrypoint annotation of its own.
Pinning it keeps the ACME challenge reachable as plain HTTP on `:80`, where its exact
`/.well-known/acme-challenge/<token>` rule out-ranks the low-priority catch-all redirect.

#### Scenario: Solver Ingress serves the challenge on :80 despite the websecure default
- **WHEN** cert-manager creates an HTTP-01 solver Ingress from a configured issuer
- **THEN** the solver Ingress carries `router.entrypoints: web` and binds `:80`
- **AND** `http://<custom-domain>/.well-known/acme-challenge/<token>` is served as plain HTTP and the
  certificate can be issued

### Requirement: Freepod Traefik is a Terraform-managed Helm release, not the k3s-bundled addon
Freepod Traefik SHALL be deployed as a **Terraform-managed Helm release** (`tf/deps/system/helm/traefik/`,
an upstream-chart `helm_release`), and the **k3s-bundled Traefik SHALL be disabled** on the node via
`/etc/rancher/k3s/config.yaml` (`disable: [traefik]`). No file under
`/var/lib/rancher/k3s/server/manifests/` SHALL define Traefik or a `HelmChartConfig/traefik`. Terraform
is therefore the single source of truth for freepod Traefik's chart version and configuration; the prior
pattern of amending the bundled chart via a `HelmChartConfig` (`kubernetes_manifest.traefik_config`) is
removed.

The Helm release's `values.yaml` SHALL reproduce the existing TLS-termination configuration with no
behavioral change: the `*.freepod.eu` wildcard as the default certificate store, PROXY-protocol trust
from the HAProxy edge IP on `web` and `websecure` (no blanket `forwardedheaders.insecure`), a
`LoadBalancer` Service with `externalTrafficPolicy: Local` owning the node's `:80/:443`, `websecure`
as the default entrypoint, the `kubernetesIngressNginx` provider and `allowExternalNameServices`, the
`traefik` IngressClass as default, and no entrypoint-level HTTP→HTTPS redirect.

#### Scenario: Terraform owns Traefik and the bundled addon is disabled
- **WHEN** the freepod node's k3s configuration is inspected after this change
- **THEN** `/etc/rancher/k3s/config.yaml` disables the bundled Traefik, so k3s renders no Traefik
  addon manifest under `/var/lib/rancher/k3s/server/manifests/` (disabling via the `config.yaml`
  `disable` list writes no `traefik.yaml`/`.skip`; k3s simply never deploys the bundled Traefik)
- **AND** Traefik runs from the Terraform `helm_release`, and no `HelmChartConfig/traefik` or
  host `traefik-config.yaml` manifest exists

#### Scenario: Behavior is preserved after the migration
- **WHEN** an external client connects to `https://<app>.freepod.eu` through the HAProxy edge after cutover
- **THEN** the self-managed Traefik terminates TLS with the `*.freepod.eu` wildcard default certificate,
  strips the edge's PROXY-protocol header (trusted via `proxyProtocol.trustedIPs`), and routes to the app
- **AND** the observable behavior is identical to the pre-migration bundled-chart configuration

### Requirement: Freepod Traefik configuration survives a k3s restart
A restart of `k3s.service` SHALL preserve freepod Traefik's configuration intact — because Terraform
is the sole owner and no host manifest defines Traefik. Whether triggered by Ubuntu
unattended-upgrades + needrestart, a reboot, or a manual restart, the configuration MUST NOT be
reverted by the k3s `deploy` addon controller, which has nothing to replay for Traefik on startup.

#### Scenario: Restart does not revert the config
- **WHEN** `k3s.service` is restarted on the freepod node
- **THEN** the self-managed Traefik and its configuration (PROXY-protocol trust, wildcard default cert,
  `externalTrafficPolicy: Local`, websecure default) remain in place
- **AND** `https://freepod.eu` continues to serve valid TLS with no `record overflow` / plaintext-on-443
  regression, and no bundled Traefik or `HelmChartConfig/traefik` is recreated

### Requirement: The ingress controller reads its default store from one named namespace

The ingress controller MUST be configured with the namespace its `default` certificate store is
read from, and that configuration MUST name the namespace holding the store.

Left unset, a store named `default` is honoured wherever it is found — and when two exist, none
of them is: the controller reports the ambiguity and serves its own self-signed certificate for
every hostname it hosts, which is a whole-fleet outage produced by creating one object. Naming
the namespace makes a store outside it inert instead, which is what allows the store to be built
and inspected in a new namespace while the old one is still serving, and the move between them to
be a single reversible change to this value rather than an ordering no ordering makes safe.

#### Scenario: A store outside the named namespace is ignored

- **WHEN** a certificate store named `default` exists in a namespace other than the configured one
- **THEN** it has no effect on what is served, and no ambiguity is reported

#### Scenario: Moving the store is moving the pointer

- **WHEN** the store's namespace changes
- **THEN** the change is made by naming the new namespace, only once a valid store exists there
- **AND** every connection is served a valid certificate throughout, because the value moves
  between two working states

#### Scenario: The configured namespace always holds a store

- **WHEN** the ingress controller's configuration is inspected
- **THEN** the namespace it names contains a `default` store carrying a default certificate,
  because a named namespace holding none leaves it with no default certificate at all
