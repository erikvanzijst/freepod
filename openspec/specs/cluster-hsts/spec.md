# cluster-hsts Specification

## Purpose

Emit a strict `Strict-Transport-Security` policy on every HTTPS app response
served by freepod's Traefik, using a single shared middleware so no app needs
per-app HSTS configuration, while leaving the plain-HTTP request path (ACME
HTTP-01 challenges and the HTTP->HTTPS redirect) untouched.

## Requirements

### Requirement: Cluster-wide HSTS header on HTTPS responses

The platform SHALL emit a `Strict-Transport-Security` response header on every
app response served over the `websecure` (:443) entrypoint, without any
per-app configuration. The header value MUST correspond to a one-year policy
with subdomains and preload enabled:
`max-age=31536000; includeSubDomains; preload`.

#### Scenario: HSTS header present on an HTTPS app response

- **WHEN** a client requests any freepod app over HTTPS
  (e.g. `curl -sI https://keycloak.freepod.eu`)
- **THEN** the response includes the header
  `strict-transport-security: max-age=31536000; includeSubDomains; preload`

### Requirement: HSTS is applied via a shared Traefik middleware

The platform SHALL implement the HSTS header with a single Traefik `headers`
Middleware named `headers-hsts` in the `kube-system` namespace, applied as a
default middleware on the `websecure` entrypoint. The middleware SHALL set
`stsSeconds = 31536000`, `stsIncludeSubdomains = true`, `stsPreload = true`,
and `forceSTSHeader = true`, so the header is emitted even for plain-HTTP
requests that Traefik forwards after TLS termination.

#### Scenario: A single default middleware covers all apps

- **WHEN** a new app Ingress is deployed with no explicit middleware annotation
- **THEN** its HTTPS responses carry the HSTS header because it inherits the
  `headers-hsts` default middleware from the `websecure` entrypoint, with no
  per-app change required

### Requirement: The plain-HTTP entrypoint is not affected

The HSTS middleware SHALL NOT be attached to the `web` (:80) entrypoint, so the
plain-HTTP request path — cert-manager's ACME HTTP-01 challenge and the
HTTP->HTTPS redirect — remains unchanged.

#### Scenario: ACME HTTP-01 challenge still succeeds

- **WHEN** cert-manager serves an ACME HTTP-01 challenge on :80 for a
  custom-domain certificate
- **THEN** the challenge is answered as plain HTTP and issuance succeeds,
  because the `headers-hsts` middleware is not present on the `web` entrypoint

#### Scenario: HTTP->HTTPS redirect is unchanged

- **WHEN** a client makes a plain-HTTP request on :80 to an app host
- **THEN** it receives the existing 301 redirect to `https://<host>` with no
  HSTS header injected on the redirect path

### Requirement: Responses carry no Clear-Site-Data

The shared `headers-hsts` middleware SHALL remove any `Clear-Site-Data` header
from responses served over the `websecure` entrypoint. Its `"cookies"` value
applies beyond the host that sends it.

#### Scenario: An app sends Clear-Site-Data

- **WHEN** an app served over HTTPS answers with `Clear-Site-Data: "cookies"`
- **THEN** the response that reaches the browser carries no `Clear-Site-Data`
  header
