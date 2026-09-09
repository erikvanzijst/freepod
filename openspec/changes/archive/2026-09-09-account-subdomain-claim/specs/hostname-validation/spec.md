## REMOVED Requirements

### Requirement: Wildcard depth check rejects multi-level prefixes under configured wildcard domains
**Reason**: The depth rule inverts. A single label under a wildcard domain now names an
account, and an application is addressed one level below it, so the rule this requirement
states — that a prefix must be exactly one label — refuses the only shape a deployment can
now take. Replaced by "Wildcard depth separates accounts from applications" below.
**Migration**: `_check_wildcard_depth` in `api/app/services/hostnames.py` requires a
two-label prefix instead of a one-label prefix. Every existing deployment's hostname is
moved beneath its owner's subdomain in the same rollout, so no stored hostname is left at
the depth the new rule refuses.

### Requirement: Validation checks execute in order and short-circuit on first failure
**Reason**: The ordered sequence itself survives, but one of its steps changes meaning and
one of its scenarios describes a reason code that no longer exists. Restated as "Validation
runs its checks in order and stops at the first failure" below, with the depth step
rewritten and the `nested_subdomain` scenario dropped.
**Migration**: None beyond the depth check itself. The order of the checks and the
short-circuiting behavior are unchanged.

## MODIFIED Requirements

### Requirement: HostnameException carries a reason attribute
The `HostnameException` class in `api/app/services/errors.py` MUST have a `reason` attribute of type `str`. Valid reason values MUST be: `"invalid"`, `"reserved"`, `"in_use"`, `"claimed"`, `"not_resolving"`. `"nested_subdomain"` is retired along with the rule that produced it.

#### Scenario: Exception reason is accessible
- **WHEN** a `HostnameException` is raised with `reason="in_use"`
- **THEN** the exception's `reason` attribute equals `"in_use"`

#### Scenario: A label held as a subdomain reports its own reason
- **WHEN** a single label under a wildcard domain is checked and another account holds it
- **THEN** the exception's `reason` attribute equals `"claimed"` rather than `"in_use"`

## ADDED Requirements

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
