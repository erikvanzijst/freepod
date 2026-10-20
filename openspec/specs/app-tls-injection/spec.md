# app-tls-injection Specification

## Purpose
Expose per-app routing via a `caelus.ingress` Helm values block, mark app Ingresses as websecure-only by omitting the entrypoint annotation (so unannotated routers bind `websecure` only and HTTP falls through to a cluster-wide redirect), and wire cert-manager for custom-domain TLS.

## Requirements

### Requirement: The reconciler injects a system-controlled caelus.ingress values block
The deployment reconciler (`api/app/services/reconcile.py`) SHALL compute a `caelus.ingress` Helm
values block per deployment and merge it as a system override (highest precedence, via
`merge_values_scoped`), mirroring the existing `_build_plan_overrides` pattern. The block SHALL set
`caelus.ingress.enabled: true` (the platform exposes this deployment via an Ingress) and
`caelus.ingress.host` (the routing host and cert SAN), and SHALL classify the deployment hostname
under `caelus.ingress.tls` as **wildcard** (under the configured `settings.tenant_domain`, and so
served by the platform's default certificate) or **custom**. The key keeps the name `wildcard`
in the chart contract. The issuer name SHALL come from settings (`api/app/config.py`:
`tls_cluster_issuer`), never hardcoded in chart sources.

#### Scenario: Wildcard host injection
- **WHEN** a deployment hostname is under the tenant domain (e.g. `hw-alice.freepod.app` with tenant domain `freepod.app`)
- **THEN** `caelus.ingress` has `enabled: true`, `host` set, and `tls.wildcard: true`
- **AND** no per-app issuer or TLS secret is required (the host is served by Traefik's default
  cert store)

#### Scenario: Custom-domain host injection
- **WHEN** a deployment hostname is a custom domain (e.g. `app.example.com`)
- **THEN** `caelus.ingress` has `enabled: true`, `host` set, and `tls` with `wildcard: false`,
  `issuer` set to the HTTP-01 ClusterIssuer name, and `secretName` set to `<release-name>-tls`

### Requirement: Application Ingresses are websecure-only; redirect is cluster-wide
Product chart Ingresses SHALL NOT carry the
`traefik.ingress.kubernetes.io/router.entrypoints: websecure` annotation, and SHALL NOT render any
per-app redirect (no `redirectScheme` middleware, no redirect-only Ingress). HTTPS-only routing is
provided by the freepod Traefik default entrypoint instead: with `websecure` marked as the default
entrypoint (see `freepod-tls-termination`), an app Ingress without an explicit entrypoint annotation
binds `websecure` only, so its plain-HTTP `:80` traffic falls through to the single cluster-wide
redirect — a low-priority web-only catch-all IngressRoute + `redirectScheme` Middleware on freepod
Traefik, which cert-manager's longer solver rule out-ranks.

#### Scenario: TLS-enabled app Ingress carries no entrypoint annotation
- **WHEN** a chart is rendered with `caelus.ingress.enabled: true` (wildcard or custom host)
- **THEN** the Ingress carries no `traefik.ingress.kubernetes.io/router.entrypoints` annotation
- **AND** it contains no `redirectScheme` middleware or redirect-only Ingress

#### Scenario: Plain-HTTP app traffic is redirected by the cluster-wide route
- **WHEN** a request hits an app host on `:80`
- **THEN** the web-only catch-all IngressRoute redirects it to `https://host` (no internal port)
- **AND** an exact ACME challenge path on `:80` is still served (its rule out-ranks the catch-all)

### Requirement: Custom-domain Ingresses request and serve a per-app certificate
The system SHALL render, for custom-domain deployments (where `caelus.ingress.enabled` is true and
`caelus.ingress.tls.wildcard` is false), a chart Ingress carrying the
`cert-manager.io/cluster-issuer` annotation (issuer from `caelus.ingress.tls.issuer`) and a `tls:`
block referencing `caelus.ingress.tls.secretName` for `caelus.ingress.host`, so cert-manager
(ingress-shim) provisions an HTTP-01 certificate. Wildcard-host Ingresses SHALL NOT carry the issuer
annotation or a per-app `tls:` secret, because the default cert store serves them.

#### Scenario: Custom-domain chart renders cert-manager wiring
- **WHEN** a chart is rendered with `caelus.ingress.tls.wildcard: false`
- **THEN** the Ingress has `cert-manager.io/cluster-issuer: <issuer>` and a `tls:` entry with
  the host and `secretName`
- **AND** cert-manager issues and stores the certificate in the deployment namespace

#### Scenario: Wildcard-host chart omits per-app cert wiring
- **WHEN** a chart is rendered with `caelus.ingress.tls.wildcard: true`
- **THEN** the Ingress has no cert-manager issuer annotation and no per-app `tls:` secret

### Requirement: Chart schemas and packages accept the caelus.ingress block
Every product chart's `values.schema.json` SHALL declare the `caelus.ingress` object (with a nested
`tls` object) so the `additionalProperties: false` schemas accept it and `validate_user_values`
passes; each `values.yaml` SHALL provide a safe default (`caelus.ingress.enabled: false` with an
empty `caelus.ingress.tls: {}` so the `not .tls.wildcard` access stays nil-safe) so charts render
standalone; and each chart version SHALL be bumped and its `.tgz` repackaged for the reconciler to
install.

#### Scenario: Standalone render without the reconciler
- **WHEN** `helm template` is run on a chart without reconciler-injected values
- **THEN** the chart renders successfully using `caelus.ingress.enabled: false` defaults (no TLS
  block, no redirect middleware)

#### Scenario: Schema accepts injected values
- **WHEN** the reconciler injects a populated `caelus.ingress` block
- **THEN** `validate_user_values` and Helm accept it against the chart's `values.schema.json`
