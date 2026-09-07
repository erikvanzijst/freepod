## MODIFIED Requirements

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
