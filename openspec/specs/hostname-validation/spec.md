# hostname-validation Specification

## Purpose
What makes a hostname usable for a deployment, and in what order the question is
asked. Under a configured wildcard domain the answer turns on depth: one label
names an account, two name one of its applications. Everything else -- format,
the reserved list, availability, and the DNS records a custom domain must carry --
hangs off that.

## Requirements

### Requirement: Hostname validation service exposes a single public function
The system MUST provide a hostname validation function `require_valid_hostname_for_deployment(session, fqdn, *, handle)` in `api/app/services/hostnames.py` that validates whether a given hostname can be used for a deployment owned by an account holding `handle` (or none). The function MUST lowercase the value and complete a bare label (see *A bare application label is completed beneath the owner's handle*) before performing any checks. The function MUST return the completed, lowercased FQDN on success or raise a `HostnameException` with a `reason` attribute on failure.

#### Scenario: Valid hostname passes all checks
- **WHEN** `require_valid_hostname_for_deployment` is called with a well-formed custom FQDN that is not under a platform domain, not in use by any active deployment, and points at the platform in DNS (a CNAME to the CNAME target, or A/AAAA records on its addresses)
- **THEN** the function returns that FQDN

#### Scenario: Mixed-case hostname is normalized before checks
- **WHEN** `require_valid_hostname_for_deployment` is called with `"Foo.Dev.Deprutser.Be"`
- **THEN** the function normalizes the FQDN to `"foo.dev.deprutser.be"` before running any check

#### Scenario: Mixed-case hostname detected as in use
- **WHEN** `require_valid_hostname_for_deployment` is called with `"FOO.dev.deprutser.be"` and an active deployment has hostname `"foo.dev.deprutser.be"`
- **THEN** the function raises `HostnameException` with `reason="in_use"`

#### Scenario: Invalid hostname format
- **WHEN** `require_valid_hostname_for_deployment` is called with an FQDN that does not conform to RFC 952/1123 (e.g., exceeds 253 characters, contains invalid characters, has labels longer than 63 characters, or has labels with leading/trailing hyphens)
- **THEN** the function raises `HostnameException` with `reason="invalid"`

#### Scenario: Reserved hostname matched case-insensitively
- **WHEN** `require_valid_hostname_for_deployment` is called with `"SMTP.freepod.eu"` and `"freepod.eu"` is a platform domain that is not the tenant domain
- **THEN** the function raises `HostnameException` with `reason="reserved"`

#### Scenario: Hostname already in use
- **WHEN** `require_valid_hostname_for_deployment` is called with an FQDN that is the `hostname` of an active deployment (status not `deleted`)
- **THEN** the function raises `HostnameException` with `reason="in_use"`

#### Scenario: Hostname does not point at the platform
- **WHEN** `require_valid_hostname_for_deployment` is called with a custom FQDN whose CNAME does not point exactly to the CNAME target, or that has no CNAME and whose A/AAAA records are not all among the CNAME target's addresses
- **THEN** the function raises `HostnameException` with `reason="not_resolving"`

#### Scenario: Hostname does not exist in DNS
- **WHEN** `require_valid_hostname_for_deployment` is called with a custom FQDN that has no DNS records at all
- **THEN** the function raises `HostnameException` with `reason="not_resolving"`

### Requirement: DNS check validates hostname points at the platform
The **CNAME target** is the tenant domain, or `settings.domain` where no tenant domain is configured. It is what custom domains are told to point at.

The DNS check MUST accept a custom hostname that reaches the platform in either of two ways: a CNAME record whose target is the CNAME target, or — the only form a domain apex can take, and what CNAME flattening, ALIAS and ANAME records answer with — A/AAAA records on the platform's own addresses. It MUST use the `dnspython` library.

To avoid being misled by a recursive resolver's negative cache (a freshly created record would otherwise be masked by a previously cached "no record" answer until its TTL expires), every lookup MUST query the queried name's zone's authoritative nameservers directly when they can be determined, and MAY fall back to the default system resolver only when those nameservers cannot be determined or reached. A negative answer (NXDOMAIN or no records of the type) from an authoritative nameserver is final and MUST NOT be retried through the system resolver.

The check MUST first query the FQDN's CNAME record. When one exists, its target (trailing dot stripped, lowercased) MUST equal the CNAME target exactly, and the FQDN's addresses MUST NOT be consulted: a CNAME elsewhere is refused even when the name it leads to shares the platform's addresses.

When the FQDN has no CNAME, the check MUST collect its A and AAAA records and the platform's addresses, which are the A and AAAA records the CNAME target itself resolves to at check time, following any CNAME chain. The platform's addresses MUST NOT be hardcoded, and MUST be read from the CNAME target's authoritative nameservers by the same rule, so the cluster's own resolver cannot substitute a different answer. Addresses MUST be compared as IP addresses, not as text. The check MUST pass only when the FQDN has at least one A or AAAA record and **every** one of them is among the platform's addresses. One foreign address refuses the hostname, because the clients — and the certificate authority's HTTP-01 validation — that reach it would not reach the platform. A hostname MAY carry only A records or only AAAA records, and need not carry every address family the platform does.

The check MUST be skipped when `settings.domain` is an empty string, or when the FQDN is under the tenant domain (the platform serves those names from its own static record). Any failure — a CNAME elsewhere, no records, a foreign address, NXDOMAIN, the platform's own addresses being unresolvable, or a lookup that no server answers — MUST raise `HostnameException(reason="not_resolving")`.

#### Scenario: Freshly created record is picked up without waiting for cache expiry
- **WHEN** an earlier check found no record (a recursive resolver would cache that negative answer), the user then creates the correct CNAME or A/AAAA records, and the check runs again
- **THEN** the check queries the zone's authoritative nameservers directly and passes, without waiting for the recursive resolver's negative cache TTL to expire

#### Scenario: Authoritative nameservers unreachable falls back to system resolver
- **WHEN** the FQDN zone's authoritative nameservers cannot be determined or reached (e.g. outbound DNS is restricted)
- **THEN** the check falls back to the default system resolver, and a definitive resolver failure still raises `HostnameException(reason="not_resolving")`

#### Scenario: CNAME points exactly to domain
- **WHEN** the FQDN has a CNAME record whose target equals the CNAME target (e.g. `"freepod.app"`)
- **THEN** the DNS check passes without looking up any addresses

#### Scenario: CNAME points to the platform domain
- **WHEN** the tenant domain is `"freepod.app"`, `settings.domain` is `"freepod.eu"`, and the FQDN has a CNAME record whose target is `"freepod.eu"`
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: CNAME points to a subdomain of domain
- **WHEN** the FQDN has a CNAME record whose target is a subdomain of the CNAME target (e.g. `"x.freepod.app"`), even one resolving to the platform's addresses
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: CNAME points to a different domain
- **WHEN** the FQDN has a CNAME record whose target is not the CNAME target
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: Apex with A records on the platform's addresses
- **WHEN** `example.com` has no CNAME and an A record whose address is one the CNAME target resolves to
- **THEN** the DNS check passes

#### Scenario: Platform domain reached through its own CNAME
- **WHEN** the CNAME target is `"dev.freepod.app"`, itself a CNAME to a name with A records, and the FQDN's A records carry those addresses
- **THEN** the DNS check passes

#### Scenario: IPv4-only hostname on a dual-stack platform
- **WHEN** the FQDN has only A records, all among the platform's addresses, and the platform also has AAAA records
- **THEN** the DNS check passes

#### Scenario: IPv6-only hostname
- **WHEN** the FQDN has only AAAA records, all among the platform's AAAA addresses
- **THEN** the DNS check passes

#### Scenario: A record pointing elsewhere
- **WHEN** the FQDN has no CNAME and an A record whose address is not one of the platform's
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: One foreign address among matching ones
- **WHEN** the FQDN's A/AAAA records include the platform's address and also any address that is not the platform's — including an AAAA record when the platform has none
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: A proxied record
- **WHEN** the FQDN sits behind a DNS provider's proxy, so its authoritative A/AAAA records are the proxy's addresses rather than the platform's
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: FQDN has no records
- **WHEN** the FQDN has neither a CNAME nor any A or AAAA record
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: FQDN does not exist in DNS
- **WHEN** DNS lookup for the FQDN returns NXDOMAIN
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: Platform addresses cannot be determined
- **WHEN** the FQDN has A records but the CNAME target resolves to no A or AAAA record
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: DNS resolver times out
- **WHEN** a lookup the check needs times out on every server it may ask
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: DNS check skipped when domain is empty
- **WHEN** `require_valid_hostname_for_deployment` is called and `settings.domain` is an empty string
- **THEN** the DNS check is skipped and the hostname passes that check

#### Scenario: DNS check skipped for wildcard subdomain
- **WHEN** the FQDN is under the tenant domain (e.g. `"photos-alice.freepod.app"` with tenant domain `"freepod.app"`)
- **THEN** the DNS check is skipped and the hostname passes that check

### Requirement: Derived hostnames are normalized to lowercase before storage
The `_derive_hostname()` function in `api/app/services/deployments.py` MUST return hostnames in lowercase form. This ensures the `DeploymentORM.hostname` column always stores the canonical lowercase representation.

#### Scenario: Mixed-case hostname from user values is lowercased
- **WHEN** a deployment is created with user values containing hostname `"MyApp.Dev.Deprutser.Be"`
- **THEN** the derived hostname stored on the deployment record is `"myapp.dev.deprutser.be"`

#### Scenario: Lowercase hostname from user values is unchanged
- **WHEN** a deployment is created with user values containing hostname `"myapp.dev.deprutser.be"`
- **THEN** the derived hostname stored on the deployment record is `"myapp.dev.deprutser.be"`

### Requirement: Validation stops at the first failing check, in a fixed order

The hostname validation MUST execute checks in the following order and MUST short-circuit
on the first failure: bare-label completion, format, then — under the tenant domain — the
tenant pattern, ownership, the preview reservation and availability; otherwise the
platform-domain refusal, availability, and DNS resolution.

#### Scenario: A platform-domain name skips availability and DNS checks
- **WHEN** a well-formed FQDN outside the tenant domain is under a platform domain
- **THEN** the function raises `HostnameException(reason="reserved")` without querying the database or performing DNS resolution

#### Scenario: Unavailable hostname skips DNS check
- **WHEN** a well-formed custom FQDN is not under a platform domain but is already in use
- **THEN** the function raises `HostnameException(reason="in_use")` without performing DNS resolution

#### Scenario: A malformed tenant label skips ownership and availability
- **WHEN** an FQDN under the tenant domain does not match the tenant pattern
- **THEN** the function raises `HostnameException(reason="invalid")` without comparing handles or querying the database

#### Scenario: Another account's handle skips availability
- **WHEN** a well-formed tenant hostname ends in a handle other than the owner's
- **THEN** the function raises `HostnameException(reason="claimed")` without querying the database

### Requirement: Hostname refusals carry a reason attribute
The `HostnameException` class in `api/app/services/errors.py` MUST have a `reason` attribute of type `str`. Valid reason values MUST be: `"invalid"`, `"reserved"`, `"in_use"`, `"claimed"`, `"not_resolving"`.

#### Scenario: Exception reason is accessible
- **WHEN** a `HostnameException` is raised with `reason="in_use"`
- **THEN** the exception's `reason` attribute equals `"in_use"`

#### Scenario: Another account's handle reports its own reason
- **WHEN** a tenant hostname ending in another account's handle is checked
- **THEN** the exception's `reason` attribute equals `"claimed"` rather than `"in_use"`

### Requirement: Preview labels are reserved under the tenant domain
A tenant hostname whose application part begins with `preview-` MUST be refused with `reason="reserved"`: `preview-<app>-<handle>.<tenant domain>` names the live preview of the application at `<app>-<handle>.<tenant domain>`, which a deployment's chart may route itself, so no deployment may claim it. The rule MUST apply case-insensitively to the start of the tenant label only, and MUST NOT apply to hostnames outside the tenant domain.

#### Scenario: Preview label under the tenant domain is refused
- **WHEN** an owner holding `alice` submits `"Preview-Studio-alice.freepod.app"` and `freepod.app` is the tenant domain
- **THEN** the function raises `HostnameException` with `reason="reserved"`

#### Scenario: The prefix must start the label
- **WHEN** the application part is `"mypreview-app"`
- **THEN** the preview rule does not refuse it

#### Scenario: Custom domains are not affected
- **WHEN** the hostname is the custom domain `"preview-app.example.com"`
- **THEN** the preview rule does not refuse it

### Requirement: A bare application label is completed beneath the owner's handle

Wherever a hostname is submitted for an owner, a lowercased value containing no dot MUST be
treated as an application label and completed to `<label>-<handle>.<tenant domain>` using
the owner's handle, before any check runs. A value containing a dot MUST be checked as given.

#### Scenario: A bare label is completed

- **WHEN** `photos` is submitted for an owner holding `alice` on a platform whose tenant
  domain is `freepod.app`
- **THEN** it is validated, and reported, as `photos-alice.freepod.app`

#### Scenario: A fully qualified name is checked as given

- **WHEN** `photos-alice.freepod.app` is submitted for an owner holding `alice`
- **THEN** it is validated as `photos-alice.freepod.app`, exactly as the bare label would be

#### Scenario: A bare label without a handle is invalid

- **WHEN** a bare label is submitted for an owner holding no handle
- **THEN** validation fails with `reason="invalid"`

### Requirement: A tenant hostname is one label ending in its owner's handle

A hostname under the tenant domain MUST be exactly one label beneath it, of the form
`<app>-<handle>`, where the handle is the text after the label's last `-`. It is refused as
`invalid` unless the application part is 1–34 characters of `[a-z0-9-]`, begins and ends with
an alphanumeric, and contains no `--`. It is refused as `claimed` when the handle is not the
owner's own.

#### Scenario: The owner's own name is accepted

- **WHEN** an owner holding `alice` submits `my-photos-alice.freepod.app` and the tenant
  domain is `freepod.app`
- **THEN** the tenant-pattern check passes, with application part `my-photos`

#### Scenario: Another account's handle is refused

- **WHEN** an owner holding `bob` submits `photos-alice.freepod.app`
- **THEN** validation fails with `reason="claimed"`

#### Scenario: A label with no handle segment is refused

- **WHEN** an owner holding `alice` submits `photos.freepod.app` or `alice.freepod.app`,
  whose labels contain no `-`
- **THEN** validation fails with `reason="invalid"`

#### Scenario: A nested name is refused

- **WHEN** an owner holding `alice` submits `a.photos-alice.freepod.app`
- **THEN** validation fails with `reason="invalid"`

#### Scenario: Double dashes are refused

- **WHEN** an owner holding `alice` submits `my--photos-alice.freepod.app`
- **THEN** validation fails with `reason="invalid"`

#### Scenario: An over-long application part is refused

- **WHEN** the application part is 35 characters long
- **THEN** validation fails with `reason="invalid"`

#### Scenario: The tenant domain itself is refused

- **WHEN** `freepod.app` is submitted and is the tenant domain
- **THEN** validation fails with `reason="invalid"`

### Requirement: Names under a platform domain are not custom domains

A hostname that is not under this environment's tenant domain but is equal to, or beneath,
any configured platform domain MUST be refused as `reserved`. The platform domains MUST be
the same in every environment and MUST include both the platform's own domain and every
tenant domain.

#### Scenario: A platform service name is refused

- **WHEN** `grafana.freepod.eu` is submitted and `freepod.eu` is a platform domain
- **THEN** validation fails with `reason="reserved"`

#### Scenario: A retired tenant hostname is refused

- **WHEN** `photos.alice.freepod.eu` is submitted
- **THEN** validation fails with `reason="reserved"`

#### Scenario: The other environment's tenant name is refused

- **WHEN** `photos-alice.freepod.app` is submitted in the environment whose tenant domain is
  `dev.freepod.app`, and `freepod.app` is a platform domain
- **THEN** validation fails with `reason="reserved"`

#### Scenario: A custom domain is unaffected

- **WHEN** `photos.example.com` is submitted
- **THEN** this rule does not refuse it, and the custom-domain checks apply
