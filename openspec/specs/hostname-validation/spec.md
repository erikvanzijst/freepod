# hostname-validation Specification

## Purpose
What makes a hostname usable for a deployment, and in what order the question is
asked. Under a configured wildcard domain the answer turns on depth: one label
names an account, two name one of its applications. Everything else -- format,
the reserved list, availability, and the CNAME a custom domain must carry --
hangs off that.

## Requirements
### Requirement: Hostname validation service exposes a single public function
The system MUST provide a hostname validation function `require_valid_hostname_for_deployment(session, fqdn)` in `api/app/services/hostnames.py` that validates whether a given FQDN can be used for a new Caelus deployment. The function MUST normalize the FQDN to lowercase before performing any checks. The function MUST return `None` on success or raise a `HostnameException` with a `reason` attribute on failure.

#### Scenario: Valid hostname passes all checks
- **WHEN** `require_valid_hostname_for_deployment` is called with a well-formed FQDN that is not reserved, not in use by any active deployment, and has a CNAME record pointing to `settings.domain`
- **THEN** the function returns `None`

#### Scenario: Mixed-case hostname is normalized before checks
- **WHEN** `require_valid_hostname_for_deployment` is called with `"Foo.Dev.Deprutser.Be"`
- **THEN** the function normalizes the FQDN to `"foo.dev.deprutser.be"` before running format, reserved, availability, and DNS checks

#### Scenario: Mixed-case hostname detected as in use
- **WHEN** `require_valid_hostname_for_deployment` is called with `"FOO.dev.deprutser.be"` and an active deployment has hostname `"foo.dev.deprutser.be"`
- **THEN** the function raises `HostnameException` with `reason="in_use"`

#### Scenario: Invalid hostname format
- **WHEN** `require_valid_hostname_for_deployment` is called with an FQDN that does not conform to RFC 952/1123 (e.g., exceeds 253 characters, contains invalid characters, has labels longer than 63 characters, or has labels with leading/trailing hyphens)
- **THEN** the function raises `HostnameException` with `reason="invalid"`

#### Scenario: Reserved hostname matched case-insensitively
- **WHEN** `require_valid_hostname_for_deployment` is called with `"SMTP.app.deprutser.be"` and `"smtp.app.deprutser.be"` is in the `reserved_hostnames` setting
- **THEN** the function raises `HostnameException` with `reason="reserved"`

#### Scenario: Hostname already in use
- **WHEN** `require_valid_hostname_for_deployment` is called with an FQDN that is the `hostname` of an active deployment (status not `deleted`)
- **THEN** the function raises `HostnameException` with `reason="in_use"`

#### Scenario: Hostname does not have a valid CNAME to the platform
- **WHEN** `require_valid_hostname_for_deployment` is called with an FQDN that has no CNAME record, or whose CNAME does not point exactly to `settings.domain`
- **THEN** the function raises `HostnameException` with `reason="not_resolving"`

#### Scenario: Hostname does not exist in DNS
- **WHEN** `require_valid_hostname_for_deployment` is called with an FQDN that has no DNS records at all
- **THEN** the function raises `HostnameException` with `reason="not_resolving"`

### Requirement: HostnameException carries a reason attribute
The `HostnameException` class in `api/app/services/errors.py` MUST have a `reason` attribute of type `str`. Valid reason values MUST be: `"invalid"`, `"reserved"`, `"in_use"`, `"claimed"`, `"not_resolving"`. `"nested_subdomain"` is retired along with the rule that produced it.

#### Scenario: Exception reason is accessible
- **WHEN** a `HostnameException` is raised with `reason="in_use"`
- **THEN** the exception's `reason` attribute equals `"in_use"`

#### Scenario: A label held as a subdomain reports its own reason
- **WHEN** a single label under a wildcard domain is checked and another account holds it
- **THEN** the exception's `reason` attribute equals `"claimed"` rather than `"in_use"`

### Requirement: DNS check validates hostname CNAME points to domain
The DNS check MUST query the CNAME record for the given FQDN using the `dnspython` library. To avoid being misled by a recursive resolver's negative cache (a freshly created CNAME would otherwise be masked by a previously cached "no record" answer until its TTL expires), the check MUST query the FQDN zone's authoritative nameservers directly when they can be determined, and MAY fall back to the default system resolver only when the authoritative nameservers cannot be determined or reached. The resolved CNAME target (trailing dot stripped, lowercased) MUST equal `settings.domain` exactly. The check MUST be skipped when `settings.domain` is an empty string, or when the FQDN falls under any configured `wildcard_domain` (i.e. the platform manages those A records directly and they are not user-delegated). Any DNS error — including no CNAME record, wrong CNAME target, NXDOMAIN, or resolver timeout — MUST raise `HostnameException(reason="not_resolving")`.

#### Scenario: Freshly created CNAME is picked up without waiting for cache expiry
- **WHEN** an earlier check found no CNAME (a recursive resolver would cache that negative answer), the user then creates the correct CNAME, and the check runs again
- **THEN** the check queries the zone's authoritative nameservers directly and passes, without waiting for the recursive resolver's negative cache TTL to expire

#### Scenario: Authoritative nameservers unreachable falls back to system resolver
- **WHEN** the FQDN zone's authoritative nameservers cannot be determined or reached (e.g. outbound DNS is restricted)
- **THEN** the check falls back to the default system resolver, and a definitive resolver failure still raises `HostnameException(reason="not_resolving")`

#### Scenario: CNAME points exactly to domain
- **WHEN** the FQDN has a CNAME record whose target equals `settings.domain` (e.g. `"freepod.eu"`)
- **THEN** the DNS check passes

#### Scenario: CNAME points to a subdomain of domain
- **WHEN** the FQDN has a CNAME record whose target is a subdomain of `settings.domain` (e.g. `"ingress.freepod.eu"`)
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: FQDN has an A record but no CNAME
- **WHEN** the FQDN resolves via A/AAAA records but has no CNAME record
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: CNAME points to a different domain
- **WHEN** the FQDN has a CNAME record whose target is unrelated to `settings.domain`
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: FQDN does not exist in DNS
- **WHEN** DNS lookup for the FQDN returns NXDOMAIN
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: DNS resolver times out
- **WHEN** the DNS resolver raises a timeout exception
- **THEN** the function raises `HostnameException(reason="not_resolving")`

#### Scenario: DNS check skipped when domain is empty
- **WHEN** `require_valid_hostname_for_deployment` is called and `settings.domain` is an empty string
- **THEN** the DNS check is skipped and the hostname passes that check

#### Scenario: DNS check skipped for wildcard subdomain
- **WHEN** the FQDN is a subdomain of a configured `wildcard_domain` (e.g. `"foo.freepod.eu"` and `wildcard_domains` contains `"freepod.eu"`)
- **THEN** the DNS check is skipped and the hostname passes that check

### Requirement: Derived hostnames are normalized to lowercase before storage
The `_derive_hostname()` function in `api/app/services/deployments.py` MUST return hostnames in lowercase form. This ensures the `DeploymentORM.hostname` column always stores the canonical lowercase representation.

#### Scenario: Mixed-case hostname from user values is lowercased
- **WHEN** a deployment is created with user values containing hostname `"MyApp.Dev.Deprutser.Be"`
- **THEN** the derived hostname stored on the deployment record is `"myapp.dev.deprutser.be"`

#### Scenario: Lowercase hostname from user values is unchanged
- **WHEN** a deployment is created with user values containing hostname `"myapp.dev.deprutser.be"`
- **THEN** the derived hostname stored on the deployment record is `"myapp.dev.deprutser.be"`

### Requirement: Wildcard depth separates accounts from applications

Under a configured wildcard domain, the prefix before the domain suffix MUST be exactly
**two** DNS labels for a deployment hostname: an application label and the account subdomain
it is deployed beneath. A prefix of one label names an account rather than an application
and MUST be refused with `HostnameException(reason="invalid")`, as MUST a prefix of three or
more labels or no prefix at all. An FQDN that does not fall under any configured wildcard
domain MUST skip this check.

The depth is the whole of the separation between the two namespaces: one label under a
wildcard domain is an account, two is one of its applications, and nothing is ever addressed
at both depths. No rule is needed to keep a subdomain and a deployment hostname from
colliding, because they cannot occupy the same name.

#### Scenario: Two-level prefix under wildcard domain passes
- **WHEN** `require_valid_hostname_for_deployment` is called with `"photos.alice.freepod.eu"` and `wildcard_domains` contains `"freepod.eu"`
- **THEN** the wildcard depth check passes and validation continues to the next check

#### Scenario: Single-level prefix under wildcard domain is rejected
- **WHEN** `require_valid_hostname_for_deployment` is called with `"alice.freepod.eu"` and `wildcard_domains` contains `"freepod.eu"`
- **THEN** the function raises `HostnameException(reason="invalid")`, because that depth names an account and not a deployment

#### Scenario: Three-level prefix under wildcard domain is rejected
- **WHEN** `require_valid_hostname_for_deployment` is called with `"a.b.alice.freepod.eu"` and `wildcard_domains` contains `"freepod.eu"`
- **THEN** the function raises `HostnameException(reason="invalid")`

#### Scenario: Bare wildcard domain with no prefix is rejected
- **WHEN** `require_valid_hostname_for_deployment` is called with `"freepod.eu"` and `wildcard_domains` contains `"freepod.eu"`
- **THEN** the function raises `HostnameException(reason="invalid")`

#### Scenario: FQDN not under any wildcard domain skips check
- **WHEN** `require_valid_hostname_for_deployment` is called with `"foo.bar.example.com"` and `wildcard_domains` contains `"freepod.eu"`
- **THEN** the wildcard depth check is skipped and validation continues to the next check

#### Scenario: Depth check is case-insensitive
- **WHEN** `require_valid_hostname_for_deployment` is called with `"Photos.Alice.Freepod.Eu"` and `wildcard_domains` contains `"freepod.eu"`
- **THEN** after lowercase normalization the depth check passes

### Requirement: Validation runs its checks in order and stops at the first failure

The hostname validation MUST execute checks in the following order: format, wildcard depth,
reserved, availability, DNS resolution. The function MUST short-circuit and raise on the
first failing check.

#### Scenario: Reserved hostname skips availability and DNS checks
- **WHEN** an FQDN is well-formed, passes the wildcard depth check, but appears in the reserved hostnames list
- **THEN** the function raises `HostnameException(reason="reserved")` without querying the database or performing DNS resolution

#### Scenario: Unavailable hostname skips DNS check
- **WHEN** an FQDN is well-formed, passes the wildcard depth check, is not reserved, but is already in use
- **THEN** the function raises `HostnameException(reason="in_use")` without performing DNS resolution

#### Scenario: Wrong depth under a wildcard domain skips reserved, availability, and DNS checks
- **WHEN** an FQDN is well-formed but its prefix under a configured wildcard domain is not exactly two labels
- **THEN** the function raises `HostnameException(reason="invalid")` without checking reserved hostnames, querying the database, or performing DNS resolution

### Requirement: A single label under a wildcard domain is a subdomain question

The system MUST provide a validation path that answers whether a single label under a
configured wildcard domain is available **as an account subdomain**, distinct from the path
that validates a deployment hostname. It MUST refuse a candidate that is malformed or
outside the length bounds (`invalid`), whose FQDN appears in `reserved_hostnames`
(`reserved`), or whose label is held by any account including a soft-deleted one
(`claimed`). It MUST NOT consult the deployments table, which holds names at the other
depth only.

#### Scenario: A free label is available
- **WHEN** `alice.freepod.eu` is checked, `freepod.eu` is a wildcard domain, and no account holds `alice`
- **THEN** the check passes

#### Scenario: A held label is refused
- **WHEN** `alice.freepod.eu` is checked and an account holds the subdomain `alice`
- **THEN** the check raises `HostnameException(reason="claimed")`

#### Scenario: A reserved name is refused as a subdomain
- **WHEN** `www.freepod.eu` is checked and it appears in `reserved_hostnames`
- **THEN** the check raises `HostnameException(reason="reserved")`
