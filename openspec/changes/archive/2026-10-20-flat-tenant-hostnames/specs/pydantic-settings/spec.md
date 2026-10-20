# Spec Delta

## ADDED Requirements

### Requirement: Settings include the tenant hostname configuration
The `CaelusSettings` class MUST include the following fields with their default values:
- `tenant_domain: str = ""` — the domain tenant hostnames are formed under (`freepod.app`, `dev.freepod.app`)
- `platform_domains: list[str] = []` — domains no custom hostname may be under
- `reserved_handles: list[str] = []` — handles no account may claim

It MUST NOT include `wildcard_domains` or `reserved_hostnames`.

#### Scenario: Platform domains configured via JSON env var
- **WHEN** `CAELUS_PLATFORM_DOMAINS='["freepod.eu","freepod.app"]'` is set
- **THEN** `get_settings().platform_domains` returns `["freepod.eu", "freepod.app"]`

#### Scenario: Hostname-related fields default to empty
- **WHEN** none of `CAELUS_TENANT_DOMAIN`, `CAELUS_PLATFORM_DOMAINS`, or `CAELUS_RESERVED_HANDLES` are set
- **THEN** `tenant_domain` is `""` and the two lists are empty

#### Scenario: Retired settings are gone
- **WHEN** the settings fields are examined
- **THEN** neither `wildcard_domains` nor `reserved_hostnames` exists

## REMOVED Requirements

### Requirement: Settings includes hostname-related configuration fields
**Reason**: `wildcard_domains` and `reserved_hostnames` are replaced.
**Migration**: See *Settings include the tenant hostname configuration*.
