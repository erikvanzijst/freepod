## MODIFIED Requirements

### Requirement: A Cloudflare DNS-01 ClusterIssuer issues the freepod wildcard certificate
The system SHALL define a Let's Encrypt **DNS-01** `ClusterIssuer` scoped to the `freepod.eu`
zone, solved through the DNS provider that serves that zone, and SHALL issue a single wildcard
`Certificate` covering `freepod.eu`, `*.freepod.eu`, and `*.dev.freepod.eu`. The provider API
token SHALL be stored as a Kubernetes Secret in the `cert-manager` namespace. A **staging**
issuer variant SHALL exist for verification.

Where the provider has no built-in cert-manager solver, the solver SHALL be its own maintained
webhook, deployed by Terraform into the `cert-manager` namespace alongside cert-manager itself,
and referenced by `groupName` and `solverName` from the issuers. A third-party webhook SHALL NOT
be substituted for a provider-maintained one: the solver is on the critical path of every
certificate the platform issues, and a webhook targeting a retired provider API fails at renewal
rather than at deploy.

The solver and the zone's nameservers are one unit. Changing either alone leaves issuance
writing challenge records into a zone that no longer answers for the name being validated, and
the failure surfaces at the next renewal rather than at the change — up to sixty days later,
with nothing connecting the two.

#### Scenario: Wildcard certificate is issued via DNS-01
- **WHEN** the wildcard `Certificate` is reconciled by cert-manager
- **THEN** cert-manager completes a DNS-01 challenge through the DNS provider's API for the
  `freepod.eu` zone
- **AND** the resulting secret contains a valid certificate for `*.freepod.eu` and
  `*.dev.freepod.eu`
- **AND** no `:80`/HTTP reachability is required for issuance

#### Scenario: Staging issuer used during rollout
- **WHEN** rollout is in progress
- **THEN** the staging DNS-01 issuer can be selected to avoid Let's Encrypt production rate limits
- **AND** switching to the production issuer and forcing re-issue yields a browser-trusted cert

#### Scenario: The solver matches the zone's nameservers
- **WHEN** the authoritative nameservers for `freepod.eu` change
- **THEN** the DNS-01 solver and its credential are changed in the same operation
- **AND** an issuance is performed immediately afterwards to prove the pairing, rather than
  waiting for a renewal to reveal it
