# Spec Delta

## ADDED Requirements

### Requirement: A DNS-01 ClusterIssuer issues the platform certificate across both zones

The system SHALL define a Let's Encrypt **DNS-01** `ClusterIssuer` with one solver per zone:
Cloudflare for `freepod.eu`, and a deSEC webhook for `freepod.app`, each selected by its
zone. It SHALL issue a single `Certificate` covering `freepod.eu`, `*.freepod.eu`,
`*.dev.freepod.eu`, `freepod.app`, `*.freepod.app` and `*.dev.freepod.app`.
Each provider's API token SHALL be a Kubernetes Secret in the `cert-manager` namespace. A
**staging** issuer variant SHALL exist.

#### Scenario: The platform certificate is issued via DNS-01 in both zones
- **WHEN** the platform `Certificate` is reconciled by cert-manager
- **THEN** challenges for `freepod.eu` names are solved through Cloudflare and challenges for
  `freepod.app` names through deSEC
- **AND** the resulting secret contains a valid certificate for every name listed above, and
  for `dev.freepod.app`
- **AND** no `:80`/HTTP reachability is required for issuance

#### Scenario: No name is listed that a wildcard already covers
- **WHEN** the platform `Certificate`'s names are inspected
- **THEN** `dev.freepod.app` is not among them, because `*.freepod.app` covers it and the
  certificate authority refuses an order listing both

#### Scenario: The deSEC token is narrowly scoped
- **WHEN** the deSEC token's policies are inspected
- **THEN** it may write TXT records in the `freepod.app` zone and nothing else

#### Scenario: Staging issuer used during rollout
- **WHEN** rollout is in progress
- **THEN** the staging DNS-01 issuer can be selected to avoid Let's Encrypt production rate limits
- **AND** switching to the production issuer and forcing re-issue yields a browser-trusted cert

## REMOVED Requirements

### Requirement: A Cloudflare DNS-01 ClusterIssuer issues the freepod wildcard certificate
**Reason**: The issuer now solves two zones, and the certificate also covers the tenant domains.
**Migration**: See *A DNS-01 ClusterIssuer issues the platform certificate across both zones*.
