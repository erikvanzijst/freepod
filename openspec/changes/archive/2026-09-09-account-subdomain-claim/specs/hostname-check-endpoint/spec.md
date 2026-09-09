## REMOVED Requirements

### Requirement: Hostname check endpoint returns usability status
**Reason**: The endpoint answers a different question. Under the new addressing scheme it
dispatches on depth — one label under a wildcard domain is an account subdomain, two is a
deployment hostname — and the deployment-side answer depends on who is asking, so it can no
longer be served anonymously. Replaced by "The hostname check answers by depth for an
authenticated caller" below.
**Migration**: `GET /api/hostnames/{fqdn}` gains `get_current_user` and leaves oauth2-proxy's
`skip_auth_routes`. No anonymous caller exists: the endpoint is reached from `HostnameField`
in the deploy dialog, from the claim dialog, and from the `freepod` client, all of which
authenticate already.

## MODIFIED Requirements

### Requirement: Hostname check response model has exactly two fields
The response model MUST contain exactly two fields: `fqdn` (string) and `reason` (string or null). No additional fields such as `valid`, `available`, `resolving`, or `usable` SHALL be included.

#### Scenario: Response shape
- **WHEN** the endpoint returns a response
- **THEN** the JSON body contains only the keys `fqdn` and `reason`

## ADDED Requirements

### Requirement: The hostname check answers by depth for an authenticated caller

The system MUST provide a `GET /api/hostnames/{fqdn}` endpoint that validates whether the
given FQDN can be used, returning the normalized (lowercased) FQDN and a reason for failure
or null on success. The endpoint MUST require authentication.

It MUST answer by depth under a configured wildcard domain: a single label is a question
about an **account subdomain**, two labels a question about a **deployment hostname**. An
FQDN outside every configured wildcard domain is a custom deployment hostname and is
answered as one. It MUST refuse a deployment hostname beneath an account subdomain the
caller does not hold, with reason `claimed`.

Authentication is required because the deployment-side answer depends on who is asking:
whether `photos.alice.freepod.eu` is usable is a different answer for Alice than for another
account.

#### Scenario: Anonymous request is refused
- **WHEN** a client sends `GET /api/hostnames/photos.alice.freepod.eu` without an authentication header
- **THEN** the request is refused rather than answered

#### Scenario: A free subdomain
- **WHEN** an authenticated client sends `GET /api/hostnames/alice.freepod.eu`, `freepod.eu` is a wildcard domain, and no account holds `alice`
- **THEN** the endpoint returns HTTP 200 with body `{"fqdn": "alice.freepod.eu", "reason": null}`

#### Scenario: A subdomain another account holds
- **WHEN** an authenticated client sends `GET /api/hostnames/alice.freepod.eu` and another account holds the subdomain `alice`
- **THEN** the endpoint returns HTTP 200 with body `{"fqdn": "alice.freepod.eu", "reason": "claimed"}`

#### Scenario: An application name beneath the caller's own subdomain
- **WHEN** the caller holds `alice` and sends `GET /api/hostnames/photos.alice.freepod.eu`, and no deployment holds that hostname
- **THEN** the endpoint returns HTTP 200 with body `{"fqdn": "photos.alice.freepod.eu", "reason": null}`

#### Scenario: An application name beneath somebody else's subdomain
- **WHEN** the caller holds `bob` and sends `GET /api/hostnames/photos.alice.freepod.eu`
- **THEN** the endpoint returns HTTP 200 with body `{"fqdn": "photos.alice.freepod.eu", "reason": "claimed"}`

#### Scenario: An application name already in use
- **WHEN** the caller holds `alice` and an active deployment holds `photos.alice.freepod.eu`
- **THEN** the endpoint returns HTTP 200 with body `{"fqdn": "photos.alice.freepod.eu", "reason": "in_use"}`

#### Scenario: Mixed-case hostname is normalized in response
- **WHEN** an authenticated client sends `GET /api/hostnames/Photos.Alice.Freepod.Eu` and the hostname passes all validation checks
- **THEN** the endpoint returns HTTP 200 with body `{"fqdn": "photos.alice.freepod.eu", "reason": null}`

#### Scenario: Invalid hostname format
- **WHEN** an authenticated client sends `GET /api/hostnames/-bad..host` and the hostname fails format validation
- **THEN** the endpoint returns HTTP 200 with body `{"fqdn": "-bad..host", "reason": "invalid"}`

#### Scenario: Reserved hostname
- **WHEN** an authenticated client sends `GET /api/hostnames/smtp.freepod.eu` and the hostname is in the reserved list
- **THEN** the endpoint returns HTTP 200 with body `{"fqdn": "smtp.freepod.eu", "reason": "reserved"}`

#### Scenario: Custom hostname does not have a CNAME to the platform domain
- **WHEN** an authenticated client sends `GET /api/hostnames/example.com` and the FQDN has no CNAME record pointing to `settings.domain`
- **THEN** the endpoint returns HTTP 200 with body `{"fqdn": "example.com", "reason": "not_resolving"}`

### Requirement: The public route list drops the hostname check

`GET /api/hostnames/{fqdn}` MUST be removed from oauth2-proxy's `skip_auth_routes`, so the
edge and the application agree on which routes are public. `GET /api/domains` and
`GET /api/cname-target` remain public: neither is shaped by identity.

The two lists disagreeing is a failure this deployment has met before, and an endpoint that
requires a caller while the edge lets anonymous requests reach it answers every one of them
with a refusal that looks like a platform fault.

#### Scenario: The edge and the application agree
- **WHEN** the route table and `skip_auth_routes` are compared after this change
- **THEN** `GET /api/hostnames/{fqdn}` appears in neither as a public route
