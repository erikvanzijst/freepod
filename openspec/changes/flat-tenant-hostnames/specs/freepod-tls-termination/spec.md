# Spec Delta

## ADDED Requirements

### Requirement: Freepod Traefik terminates TLS using the platform certificate as the default
Freepod Traefik SHALL terminate TLS itself and serve the platform certificate, which covers
`freepod.eu`, `*.freepod.eu`, `*.dev.freepod.eu` and both tenant domains with their wildcards,
as the **default certificate** of its store, so tenant Ingresses need no TLS secret.

The store SHALL be a platform-owned `TLSStore` named `default` beside its certificate
secrets, not rendered by the Traefik release. Certificates are selected by server name.

#### Scenario: Tenant app served by the default certificate
- **WHEN** a TLS connection arrives at freepod Traefik with SNI `<app>-<handle>.freepod.app` or
  `<app>-<handle>.dev.freepod.app` and the app's Ingress has no explicit `tls:` secret
- **THEN** Traefik serves the default certificate and routes to the app
- **AND** no per-namespace certificate or secret reflection is needed for tenant apps

#### Scenario: Platform host served by the default certificate
- **WHEN** a TLS connection arrives with SNI `freepod.eu` or `<service>.freepod.eu`
- **THEN** Traefik serves the default certificate

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

## REMOVED Requirements

### Requirement: Freepod Traefik terminates TLS using the wildcard as the default certificate
**Reason**: The default certificate now also covers the tenant domains, which serve every tenant application.
**Migration**: See *Freepod Traefik terminates TLS using the platform certificate as the default*.
