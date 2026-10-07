## MODIFIED Requirements

### Requirement: The S3 API is reachable externally over TLS at a wildcard-covered hostname

Each environment's Garage S3 API SHALL be published through Traefik at `blob.<environment
domain>` — `blob.freepod.eu` for prod, `blob.dev.freepod.eu` for dev — and served over HTTPS.
In-cluster-only reachability is not sufficient: the primary client is an external CLI running on
a developer's laptop.

The hostname SHALL be a **single-label** subdomain of the environment's domain. Traefik's default
certificate store serves the platform wildcard certificate, which covers `*.freepod.eu` and
`*.dev.freepod.eu`, for any SNI without a more specific certificate, so such a host requires
**no per-app cert-manager Certificate and no ACME challenge**. A deeper host such as
`blob.objects.freepod.eu` falls outside the wildcard and would require per-app certificate
issuance for no functional gain.

Plain HTTP requests to the host SHALL be redirected to HTTPS by the existing cluster-wide
redirect; the S3 API SHALL NOT be served unencrypted.

#### Scenario: HTTPS request reaches Garage with a valid certificate

- **WHEN** an external client issues an HTTPS request to `https://blob.freepod.eu/` or
  `https://blob.dev.freepod.eu/`
- **THEN** TLS is negotiated with a valid, publicly trusted certificate covering that host
- **AND** the request is served by Garage's S3 endpoint

#### Scenario: No per-app certificate is created

- **WHEN** the Garage Terraform module is inspected
- **THEN** it declares no cert-manager `Certificate` and no TLS secret of its own
- **AND** the ingress relies on Traefik's default wildcard certificate store

#### Scenario: HTTP is redirected, not served

- **WHEN** a plain HTTP request is made to an environment's `http://blob.<domain>/`
- **THEN** the response is a redirect to the HTTPS URL
- **AND** no S3 response body is served over the unencrypted connection

### Requirement: The S3 ingress deliberately omits the forward-auth middleware

The Garage ingress SHALL NOT attach the `forward-auth` middleware, and SHALL NOT attach any
other middleware that inspects, rewrites, adds or removes request headers, the request URI or
the query string.

This omission is deliberate and load-bearing. Garage authenticates requests with AWS SigV4,
either from an `Authorization` header or from a presigned URL's query-string signature. Routing
those requests through oauth2-proxy breaks them **twice over**: oauth2-proxy sees no session
cookie and returns `401` before Garage is ever reached, and — even if it did not — it injects
`X-Auth-Request-*` headers and alters the request, so the SigV4 signature computed by the
client no longer verifies against what Garage receives.

Because an ingress that silently lacks authentication is a landmine for the next reader, the
reason for the omission SHALL be recorded in an in-line comment on the ingress resource itself,
following the precedent set by the webhooks ingress in `tf/app/caelus/ingress.tf`, which bypasses
oauth2-proxy for the same class of reason and documents why in place.

Authentication is not weakened, only relocated: every request is verified by Garage's own SigV4
check, and the ability to obtain a presigned URL is controlled by the Caelus API.

#### Scenario: No auth middleware is attached

- **WHEN** the Garage Ingress resource is inspected
- **THEN** it carries no `forward-auth` middleware annotation
- **AND** it carries no other request-mutating middleware

#### Scenario: The omission is justified in place

- **WHEN** the Garage ingress source in `tf/app/garage/` is read
- **THEN** an in-line comment states that S3 SigV4 and presigned-URL signatures are
  incompatible with oauth2-proxy, and that the omission is intentional

#### Scenario: A signed request authenticates end to end

- **WHEN** an external client issues a SigV4-signed S3 request through an environment's
  `https://blob.<domain>` with valid credentials
- **THEN** Garage verifies the signature and serves the request
- **AND** no oauth2-proxy redirect or `401` is returned by the edge

#### Scenario: An unsigned request is rejected by Garage, not by the edge

- **WHEN** an unauthenticated request is made to a private object through the edge
- **THEN** the response is an S3-formatted access-denied error produced by Garage
- **AND** the response is not an oauth2-proxy login redirect
