## Purpose

The DNS record an account gets under the platform domain: a wildcard covering every hostname
its applications will ever have, why that record is load-bearing rather than convenient, and
how the platform reaches whichever DNS provider serves the zone.

## ADDED Requirements

### Requirement: An account that deploys gets a wildcard record

The platform MUST create a wildcard address record for `*.<subdomain>.<platform domain>` when
an account first deploys, resolving to the same target the platform's own wildcard resolves
to. Creation MUST be idempotent, so that a repeated reconcile neither duplicates nor rewrites
it.

The record MUST NOT be deleted — not when a deployment is removed, and not when the account
is closed. An account's subdomain is never released, so the record has nothing to be reclaimed
for, and deleting it would take down every application under it.

#### Scenario: The record exists before the account's first application

- **WHEN** an account with no prior deployment reconciles its first one
- **THEN** a wildcard record for its subdomain exists, resolving to the platform's ingress

#### Scenario: Reconciling again changes nothing

- **WHEN** the same account reconciles a further deployment
- **THEN** the existing record is left as it is, and no second record is created

#### Scenario: Removing a deployment leaves the record

- **WHEN** an account's last deployment is deleted
- **THEN** its wildcard record remains

### Requirement: The record must exist before the certificate is requested

The platform MUST create the account's wildcard record before requesting its certificate,
within the same reconcile, and MUST NOT request a certificate for an account whose record it
has not established.

This ordering is not stylistic, but the hazard it guards against is the DNS standard's
behavior rather than every server's. Issuing the certificate writes an ACME challenge record at
`_acme-challenge.<subdomain>.<platform domain>`, which makes `<subdomain>.<platform domain>`
exist as an empty non-terminal. RFC 4592 says a wildcard answers only for names that do not
themselves exist, so on a conformant server `*.<platform domain>` stops answering for everything
under that name the moment the challenge is written, and only the account's own wildcard
continues to.

Measured on Cloudflare, 2026-09-08: it does not implement that rule for empty non-terminals — a
live challenge record beneath an account's name left every name under it resolving from
`*.<platform domain>`. So on the platform's current provider the record is redundant, and the
requirement stands anyway. It is one record per account either way, it is what makes the
platform's behavior independent of a provider quirk, and a provider change is the moment the
hazard becomes real for every account that does not already hold one.

#### Scenario: Certificate issuance does not interrupt the account's applications

- **WHEN** an account's certificate is issued or renewed, and a challenge record is written
  beneath its subdomain
- **THEN** its application hostnames continue to resolve throughout, on a server that stops
  synthesizing from the platform wildcard as well as on one that does not

#### Scenario: A certificate is not requested without the record

- **WHEN** the record cannot be created
- **THEN** no certificate is requested for that account

#### Scenario: The rationale survives the record

- **WHEN** an operator reviews the zone and finds a wildcard record that appears redundant
  alongside the platform's own — and confirms on the current provider that it is
- **THEN** what is documented where the record is created says why it is kept regardless, so
  that testing the hazard and not reproducing it is not grounds for removing the record

### Requirement: Only the wildcard is created, not the account's own name

The platform MUST create the wildcard record and MUST NOT create an address record for
`<subdomain>.<platform domain>` itself.

The account's own name is reserved and serves nothing, and a DNS zone's per-zone record limit
is the platform's account ceiling — one record per account rather than two doubles how far
that ceiling is. The consequence is understood and accepted: nothing is published at the
account's bare name. What it resolves to is then whatever the platform's own wildcard makes of
it, which differs by provider and is not something the platform arranges either way.

#### Scenario: Nothing is published at the account's bare name

- **WHEN** the zone is inspected for `<subdomain>.<platform domain>`
- **THEN** no record has been created for it, and this is the intended behavior

### Requirement: The DNS provider is reached through an adapter

All DNS writes MUST go through a single narrow interface that the rest of the platform depends
on, with one implementation per provider selected by configuration. No provider's API, SDK,
credential shape or error vocabulary may appear outside that implementation.

The platform's DNS provider is expected to change, and the reconciler should not know that it
did. The interface needs only what the platform actually does: ensure a wildcard record
exists for a name, and report whether one does.

#### Scenario: Changing provider is one implementation

- **WHEN** the platform moves to a different DNS provider
- **THEN** a new implementation of the interface is added and selected by configuration
- **AND** the reconciler is unchanged

#### Scenario: Provider details do not leak

- **WHEN** the platform's code outside the adapter is inspected
- **THEN** it contains no provider-specific client, credential, or error type

### Requirement: A failed DNS write is visible and does not corrupt state

When the record cannot be created, the platform MUST record the failure where an operator will
see it, MUST NOT request a certificate for that account, and MUST leave the account in a state
where a later reconcile retries from the beginning.

#### Scenario: A provider outage is retried, not absorbed

- **WHEN** the DNS provider is unavailable during a reconcile
- **THEN** the failure is reported, no certificate is requested, and a subsequent reconcile
  attempts the record again
