## ADDED Requirements

### Requirement: A label held as an account's subdomain is not a deployable hostname

Hostname validation MUST refuse an FQDN formed by placing a single label under a configured
wildcard domain when that label is held by any account as its subdomain, raising
`HostnameException` with reason `claimed`. The check MUST NOT apply to hostnames outside the
configured wildcard domains, which are the user's own DNS and not the platform's to
allocate.

Without this, a deployment can take `alice.freepod.eu` while `alice` is somebody's
subdomain, and every application that account later deploys is addressed beneath a name
answered by a stranger's app.

#### Scenario: A claimed label is refused as a deployment hostname

- **WHEN** an account holds the subdomain `alice` and a deployment hostname `alice.freepod.eu`
  is validated
- **THEN** the function raises `HostnameException` with `reason="claimed"`

#### Scenario: The holder's own label is refused too

- **WHEN** the account holding `alice` validates `alice.freepod.eu` for one of its own
  deployments
- **THEN** the function raises `HostnameException` with `reason="claimed"`, because the label
  names the account's namespace rather than any one deployment in it

#### Scenario: A custom domain is unaffected

- **WHEN** `alice.example.com` is validated and `example.com` is not a configured wildcard
  domain
- **THEN** the claimed-subdomain check does not apply

## MODIFIED Requirements

### Requirement: Validation checks execute in order and short-circuit on first failure
The hostname validation MUST execute checks in the following order: format, wildcard depth, reserved, claimed subdomain, availability, DNS resolution. The function MUST short-circuit and raise on the first failing check.

The claimed-subdomain check sits after reserved and before availability: it is a question about accounts rather than about deployments, so it is answered before the deployments table is consulted, and after the platform's own names have been excluded.

#### Scenario: Reserved hostname skips availability and DNS checks
- **WHEN** an FQDN is well-formed, passes wildcard depth check, but appears in the reserved hostnames list
- **THEN** the function raises `HostnameException(reason="reserved")` without querying the database or performing DNS resolution

#### Scenario: Claimed subdomain skips availability and DNS checks
- **WHEN** an FQDN is well-formed, passes the wildcard depth check, is not reserved, but its single label under a wildcard domain is held by an account
- **THEN** the function raises `HostnameException(reason="claimed")` without checking deployment availability or performing DNS resolution

#### Scenario: Unavailable hostname skips DNS check
- **WHEN** an FQDN is well-formed, passes wildcard depth check, not reserved, not claimed, but already in use
- **THEN** the function raises `HostnameException(reason="in_use")` without performing DNS resolution

#### Scenario: Nested subdomain under wildcard domain skips reserved, availability, and DNS checks
- **WHEN** an FQDN is well-formed but has a multi-level prefix under a configured wildcard domain
- **THEN** the function raises `HostnameException(reason="nested_subdomain")` without checking reserved hostnames, querying the database, or performing DNS resolution

### Requirement: HostnameException carries a reason attribute
The `HostnameException` class in `api/app/services/errors.py` MUST have a `reason` attribute of type `str`. Valid reason values MUST be: `"invalid"`, `"reserved"`, `"claimed"`, `"in_use"`, `"not_resolving"`, `"nested_subdomain"`.

#### Scenario: Exception reason is accessible
- **WHEN** a `HostnameException` is raised with `reason="in_use"`
- **THEN** the exception's `reason` attribute equals `"in_use"`

#### Scenario: A claimed label reports its own reason
- **WHEN** a hostname is refused because its label is held as an account's subdomain
- **THEN** the exception's `reason` attribute equals `"claimed"` rather than `"in_use"` or `"reserved"`
