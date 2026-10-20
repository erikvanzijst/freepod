# Spec Delta

## ADDED Requirements

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
- **WHEN** an authenticated client sends `GET /api/hostnames/example.com` and the FQDN has neither a CNAME record pointing to the CNAME target (see `hostname-validation`) nor A/AAAA records that are all among the CNAME target's addresses
- **THEN** the endpoint returns HTTP 200 with `fqdn` `example.com`, `usable` false, and `reason` `not_resolving`

### Requirement: Hostname check response reports the name, usability and reason

The response MUST contain exactly three fields: `fqdn` (the completed, lowercased name that
was checked), `usable` (boolean), and `reason` (null when usable, otherwise one of
`invalid`, `reserved`, `in_use`, `claimed`, `not_resolving`). A refusal MUST be reported in
a 200 body, not as an error status.

#### Scenario: Response shape
- **WHEN** the endpoint returns a response
- **THEN** the JSON body contains only the keys `fqdn`, `usable` and `reason`

### Requirement: The CNAME target is the tenant domain

`GET /api/cname-target` MUST return the CNAME target, the tenant domain (see
`hostname-validation`), and an empty string when no platform domain is configured.

#### Scenario: The tenant domain is advertised
- **WHEN** the tenant domain is `dev.freepod.app` and `settings.domain` is `dev.freepod.eu`
- **THEN** `GET /api/cname-target` returns `"dev.freepod.app"`

## REMOVED Requirements

### Requirement: Hostname check response model has exactly two fields
**Reason**: It never matched the response, which has always carried `usable` as well.
**Migration**: See *Hostname check response reports the name, usability and reason*.

### Requirement: The hostname check answers by depth for an authenticated caller
**Reason**: Tenant hostnames are flat, and handle availability is answered by a dry-run claim.
**Migration**: See *The hostname check answers for the authenticated caller*, and
`account-handle` for handle availability.
