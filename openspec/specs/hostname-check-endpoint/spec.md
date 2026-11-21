# hostname-check-endpoint Specification

## Purpose
The endpoint clients ask before committing to a name. It validates without
reserving anything, answers by depth under a wildcard domain, and reports a
refusal as a machine-readable reason in a 200 body rather than as an error
status.

## Requirements

### Requirement: CNAME target endpoint exposes the platform domain
The system MUST provide a public (unauthenticated) `GET /api/cname-target` endpoint that returns the platform's domain (`settings.domain`) as a JSON string, so the UI can render environment-correct DNS setup instructions: the CNAME target a custom hostname points at, and the name whose addresses an apex's A/AAAA records carry. It MUST return an empty string when the domain is unconfigured.

#### Scenario: Returns the configured domain
- **WHEN** a client sends `GET /api/cname-target` and `settings.domain` is `"dev.freepod.eu"`
- **THEN** the endpoint returns HTTP 200 with body `"dev.freepod.eu"`

#### Scenario: Returns empty string when unconfigured
- **WHEN** a client sends `GET /api/cname-target` and `settings.domain` is empty
- **THEN** the endpoint returns HTTP 200 with body `""`

### Requirement: Hostname check endpoint is synchronous
The `GET /api/hostnames/{fqdn}` endpoint MUST be implemented as a synchronous endpoint (`def`, not `async def`) so that FastAPI dispatches it to a threadpool and database access does not block the event loop.

#### Scenario: Endpoint handles concurrent requests
- **WHEN** multiple clients call the hostname check endpoint simultaneously
- **THEN** each request runs in its own thread and does not block others

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

### Requirement: The hostname check answers for the authenticated caller

`GET /api/hostnames/{value}` MUST require authentication and validate `value` as a
deployment hostname owned by the caller, by the rules in `hostname-validation`. A bare
application label MUST be completed beneath the caller's handle, and a value with a dot is
checked as given. It MUST NOT answer questions about handles.

#### Scenario: Anonymous request is refused
- **WHEN** a client sends `GET /api/hostnames/photos` without an authentication header
- **THEN** the request is refused rather than answered

#### Scenario: A bare label is completed and checked
- **WHEN** the caller holds `alice`, the tenant domain is `freepod.app`, and no deployment holds `photos-alice.freepod.app`, and the caller sends `GET /api/hostnames/photos`
- **THEN** the endpoint returns HTTP 200 with `fqdn` `photos-alice.freepod.app`, `usable` true, and `reason` null

#### Scenario: The caller's own fully qualified name
- **WHEN** the caller holds `alice` and sends `GET /api/hostnames/photos-alice.freepod.app`, and no deployment holds it
- **THEN** the endpoint returns HTTP 200 with `fqdn` `photos-alice.freepod.app`, `usable` true, and `reason` null

#### Scenario: A name ending in somebody else's handle
- **WHEN** the caller holds `bob` and sends `GET /api/hostnames/photos-alice.freepod.app`
- **THEN** the endpoint returns HTTP 200 with `usable` false and `reason` `claimed`

#### Scenario: An application name already in use
- **WHEN** the caller holds `alice` and an active deployment holds `photos-alice.freepod.app`
- **THEN** the endpoint returns HTTP 200 with `usable` false and `reason` `in_use`

#### Scenario: Mixed-case input is normalized in the response
- **WHEN** the caller holds `alice` and sends `GET /api/hostnames/Photos` and the name passes all checks
- **THEN** the response's `fqdn` is `photos-alice.freepod.app`

#### Scenario: Invalid hostname format
- **WHEN** an authenticated client sends `GET /api/hostnames/-bad..host`
- **THEN** the endpoint returns HTTP 200 with `fqdn` `-bad..host`, `usable` false, and `reason` `invalid`

#### Scenario: A name under a platform domain
- **WHEN** an authenticated client sends `GET /api/hostnames/smtp.freepod.eu` and `freepod.eu` is a platform domain
- **THEN** the endpoint returns HTTP 200 with `usable` false and `reason` `reserved`

#### Scenario: Custom hostname does not point at the platform domain
- **WHEN** an authenticated client sends `GET /api/hostnames/example.com` and the FQDN has neither a CNAME record pointing to the CNAME target (see `hostname-validation`), A/AAAA records that are all among the CNAME target's addresses, nor A/AAAA records that are all Cloudflare's
- **THEN** the endpoint returns HTTP 200 with `fqdn` `example.com`, `usable` false, and `reason` `not_resolving`

#### Scenario: A proxied hostname with its ownership record
- **WHEN** the caller holds `alice`, the CNAME target is `freepod.app`, and `photos.example.com` is proxied through Cloudflare with the TXT record `_freepod.photos.example.com` holding `alice.freepod.app`
- **THEN** the endpoint returns HTTP 200 with `usable` true, `reason` null, `proxy` `cloudflare`, and `ownership_record` `{"name": "_freepod.photos.example.com", "value": "alice.freepod.app"}`

#### Scenario: A proxied hostname without its ownership record
- **WHEN** the same hostname has no such TXT record
- **THEN** the endpoint returns HTTP 200 with `usable` false, `reason` `ownership_unverified`, `proxy` `cloudflare`, and the same `ownership_record`

### Requirement: The hostname check answers for an existing deployment

`GET /api/hostnames/{value}` MUST accept an optional `deployment` query parameter, the UUID
of an existing deployment, and then check `value` as that deployment's update would: its own
hostname MUST NOT be reported `in_use`, and the deployment owner's handle MUST be used to
complete a bare label, check a tenant hostname and name the ownership record. The deployment
MUST be the caller's own, or the caller an administrator; otherwise the endpoint MUST return
HTTP 404.

#### Scenario: A deployment's own hostname
- **WHEN** the caller's deployment `D` holds `photos.example.com` and the caller sends `GET /api/hostnames/photos.example.com?deployment=D`
- **THEN** the endpoint returns HTTP 200 with `usable` true and `reason` null

#### Scenario: Another deployment's hostname
- **WHEN** the caller's deployment `D` exists, another deployment holds `taken.example.com`, and the caller sends `GET /api/hostnames/taken.example.com?deployment=D`
- **THEN** the endpoint returns HTTP 200 with `usable` false and `reason` `in_use`

#### Scenario: Another account's deployment
- **WHEN** a caller who is not an administrator names a deployment of another account, or one that does not exist
- **THEN** the endpoint returns HTTP 404

#### Scenario: An administrator checks for the owner
- **WHEN** an administrator sends `GET /api/hostnames/photos?deployment=D` for a deployment `D` of the account holding `owner`
- **THEN** the endpoint returns `fqdn` `photos-owner.freepod.app`, checked as that account's name

### Requirement: Hostname check response reports the name, usability, reason and proxy

The response MUST contain exactly five fields: `fqdn` (the completed, lowercased name that
was checked), `usable` (boolean), `reason` (null when usable, otherwise one of
`invalid`, `reserved`, `in_use`, `claimed`, `not_resolving`, `ownership_unverified`),
`proxy` (`cloudflare` when the name is proxied through Cloudflare, usable or refused for its
ownership record; null otherwise), and `ownership_record` (with `proxy`, the `name` and
`value` of the TXT record the name needs, as `hostname-validation` defines it, null for an
owner holding no handle; null without `proxy`). A usable name with a `proxy` is unverified:
clients MUST present it as accepted but not confirmed to reach the platform. A refusal MUST be
reported in a 200 body, not as an error status.

#### Scenario: Response shape
- **WHEN** the endpoint returns a response
- **THEN** the JSON body contains only the keys `fqdn`, `usable`, `reason`, `proxy` and `ownership_record`

#### Scenario: A direct name has no proxy
- **WHEN** the checked name is a tenant hostname, or a custom domain that points at the platform directly, or is refused for any reason but `ownership_unverified`
- **THEN** `proxy` and `ownership_record` are null

### Requirement: The CNAME target is the tenant domain

`GET /api/cname-target` MUST return the CNAME target, the tenant domain (see
`hostname-validation`), and an empty string when no platform domain is configured.

#### Scenario: The tenant domain is advertised
- **WHEN** the tenant domain is `dev.freepod.app` and `settings.domain` is `dev.freepod.eu`
- **THEN** `GET /api/cname-target` returns `"dev.freepod.app"`
