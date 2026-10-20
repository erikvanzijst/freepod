# Spec Delta

## MODIFIED Requirements

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
