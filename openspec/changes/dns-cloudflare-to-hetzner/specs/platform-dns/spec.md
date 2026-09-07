## Purpose

Where `freepod.eu`'s authoritative DNS is served and what the zone must hold for the platform to
work: the records everything else depends on, how they are managed and reviewed, and the
constraints — headroom, CAA, DNSSEC — that keep certificate issuance and mail delivery from
failing in ways that are hard to attribute back to DNS.

## ADDED Requirements

### Requirement: The zone is served by a provider with room for per-account records

`freepod.eu`'s authoritative DNS MUST be served by a provider whose per-zone record limit
accommodates one record per user account plus the platform's own, with headroom, and whose
limit can be raised on request rather than only by moving to an enterprise agreement.

Record capacity is a product constraint here, not an operational detail: the per-user subdomain
architecture allocates a DNS record per account, so the zone's ceiling is the platform's
customer ceiling. A provider whose cap is fixed by billing tier converts a growth milestone into
a migration under load.

#### Scenario: The zone has headroom for growth

- **WHEN** the provider's per-zone record limit is compared against the platform's account count
- **THEN** the limit exceeds it with room to grow, and a documented path exists to raise it

#### Scenario: Approaching the limit is visible before it is reached

- **WHEN** the number of records in the zone approaches the provider's limit
- **THEN** it is noticed from the platform's own operational signals rather than from a failed
  record creation

### Requirement: The zone's records are declared in Terraform

The platform's own DNS records MUST be declared in Terraform under `tf/deps/` and applied from
there, not entered by hand in a provider's interface.

The zone is the single point of total failure for everything the platform serves, and a set of
hand-entered records has no history, no review, and no way to answer what it contained
yesterday. Declaring it makes a change to it a diff.

Records the platform creates per user account at runtime are NOT covered by this requirement and
MUST NOT be managed by Terraform, for the same reason Terraform does not manage end-user
accounts.

#### Scenario: A platform record change is reviewable

- **WHEN** a platform DNS record is added, changed, or removed
- **THEN** it appears as a Terraform diff before it is applied

#### Scenario: Runtime records are outside Terraform

- **WHEN** the platform creates a DNS record for a user account
- **THEN** it does so through the provider's API at runtime, and Terraform neither manages nor
  destroys it

### Requirement: The zone carries the records the platform depends on

The zone MUST resolve every name the platform serves: the apex, the wildcard that answers
application hostnames, the platform's own service hostnames, the SSH edge as clients address it,
and any mail records in use. This set MUST be verified against the previous provider's zone
before the delegation moves, and again after.

Nothing announces a missing record. A zone that is 95% correct presents as one broken service
whose cause is not obviously DNS.

#### Scenario: Every name resolves identically before cutover

- **WHEN** the new provider's nameservers are queried directly for every name in the previous
  provider's zone
- **THEN** each returns the same answer as the previous provider

#### Scenario: The comparison covers every record, not the ones remembered

- **WHEN** parity is checked
- **THEN** it is checked against a full export of the previous zone rather than a list assembled
  by hand

### Requirement: A CAA record, if present, permits the platform's certificate authority

Where the zone carries a CAA record, it MUST authorize the certificate authority the platform
issues from, and this MUST be verified as part of the record parity check.

A CAA record that fails to carry over does not break resolution; it breaks certificate issuance,
weeks later, when something renews.

#### Scenario: Issuance is not blocked by a carried-over CAA record

- **WHEN** the zone's CAA records are inspected after the move
- **THEN** they permit the platform's certificate authority, or no CAA record is present

### Requirement: DNSSEC is disabled before the delegation changes

If the zone is DNSSEC-signed, signing MUST be disabled and the DS record removed at the registry,
and the DS record's TTL MUST be allowed to expire, before the nameserver delegation is changed.

A validating resolver holding a DS record for a zone now served by nameservers with different
keys does not fall back to unsigned answers — it returns SERVFAIL. The failure is total, affects
the majority of resolvers, and persists for the DS record's TTL regardless of what is corrected
afterwards. It is the one failure in this whole operation that cannot be rolled back quickly.

Re-enabling DNSSEC at the new provider is a separate, later operation.

#### Scenario: The DS record is gone before the nameservers change

- **WHEN** the delegation is changed
- **THEN** no DS record for the zone remains published at the registry, and its previous TTL has
  elapsed

#### Scenario: Re-signing is not part of the move

- **WHEN** the zone is serving from the new provider
- **THEN** enabling DNSSEC there is treated as its own change, with its own verification

### Requirement: The previous zone is retained as the rollback path

The previous provider's zone MUST be left in place and unmodified after the delegation changes,
for at least as long as the previous NS records' TTL, and MUST NOT be deleted while it is the
only way back.

Rolling back a delegation is only fast if the thing being rolled back to still exists and still
answers correctly.

#### Scenario: Rollback is a delegation change and nothing else

- **WHEN** a problem is found after cutover
- **THEN** restoring the previous nameservers at the registrar restores service, with no records
  to recreate

#### Scenario: The old zone is not edited during the overlap

- **WHEN** a record must change while both zones exist
- **THEN** it is changed in both, so that either set of nameservers gives a correct answer
