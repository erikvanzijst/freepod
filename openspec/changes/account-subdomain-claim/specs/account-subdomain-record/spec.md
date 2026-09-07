## Purpose

The subdomain an account holds: one DNS label, claimed once, never changed and never
released, under which everything that account deploys will be addressed. Recorded on the
user beside the other user-level facts, and claimed through its own resource rather than as
a field on anything else.

## ADDED Requirements

### Requirement: An account holds at most one subdomain

The user MUST carry a nullable `subdomain` column holding a single DNS label, NULL until
claimed. At most one non-deleted user MUST hold any given label, enforced by a unique index
over the lowercased value rather than by the code that writes it, mirroring the guarantee
the email column already carries.

The stored value MUST be lowercase. A claim submitted in mixed case MUST be normalized
before it is checked or stored, so that case can never distinguish two accounts.

#### Scenario: A new account holds no subdomain

- **WHEN** a user record is created
- **THEN** its subdomain is NULL

#### Scenario: Two accounts cannot hold one label

- **WHEN** a claim is written for a label a non-deleted user already holds
- **THEN** the write is refused by the database

#### Scenario: Case does not create a second label

- **WHEN** a user claims `Alice` and another user later claims `alice`
- **THEN** the first is stored as `alice` and the second is refused as taken

### Requirement: A subdomain is claimed once and never changes

A claim MUST be accepted only for an account holding none. An account that already holds a
subdomain MUST have any further claim rejected with **409**, whether the submitted label
differs from the one held or is identical to it — a claim is not idempotent, because a
repeated claim is far more likely to be a client that lost track of its state than a user
who meant it.

The platform MUST NOT provide any interface for changing or releasing a subdomain: no
endpoint, no CLI command, no administrative panel action. Correcting one is a deliberate
operator intervention against the database, because every apparent reason to make it a
feature is a reason to break somebody's addresses.

#### Scenario: A first claim is accepted

- **WHEN** a user holding no subdomain claims an available label
- **THEN** the label is stored on their record and the response reports it

#### Scenario: A second claim is refused

- **WHEN** a user who already holds a subdomain submits another claim
- **THEN** the API responds **409** and the held label is unchanged

#### Scenario: Re-submitting the held label is also refused

- **WHEN** a user submits a claim for exactly the label they already hold
- **THEN** the API responds **409** rather than reporting success

#### Scenario: No interface releases a subdomain

- **WHEN** the API surface, the CLI and the administrative interface are examined
- **THEN** none of them offers to change, clear, or transfer an account's subdomain

### Requirement: A deleted account does not release its subdomain

A subdomain MUST remain held when its account is deleted, and MUST NOT become claimable by
another account.

A released label carries the previous holder's history with it: links, bookmarks, other
people's DNS caches, and a certificate transparency record that is public and permanent.
Handing it to somebody else makes the new holder the recipient of traffic intended for the
old one.

#### Scenario: A deleted account's label stays unavailable

- **WHEN** an account holding `alice` is deleted and another user claims `alice`
- **THEN** the claim is refused as taken

### Requirement: A candidate must be a single DNS label

A claim MUST be refused unless the submitted value is one label: lowercase alphanumerics and
hyphens, beginning and ending with an alphanumeric, and short enough to leave room for an
application label and the platform domain beneath the 253-character limit on a fully
qualified name. A value containing a dot MUST be refused — an account claims a label, not a
name.

#### Scenario: A well-formed label is accepted

- **WHEN** a user claims `ada-lovelace`
- **THEN** the format check passes

#### Scenario: A dotted value is refused

- **WHEN** a user claims `ada.lovelace`
- **THEN** the claim is refused as malformed and nothing is stored

#### Scenario: A label that cannot begin or end a hostname is refused

- **WHEN** a user claims a value beginning or ending with a hyphen, or containing a
  character outside the permitted set
- **THEN** the claim is refused as malformed

### Requirement: Reserved names are refused, from the list that already exists

A claim MUST be refused when the label the user submitted, placed under a configured
wildcard domain, yields a hostname the platform already reserves.

The platform's own names are in that list because they must not be claimable as deployment
hostnames; they must not be claimable as subdomains for exactly the same reason. Deriving
the answer means one list with one purpose, rather than two that must be kept in agreement —
a failure this codebase already carries elsewhere and does not need another instance of.

#### Scenario: A platform name is refused

- **WHEN** `www.freepod.eu` is a reserved hostname and a user claims `www`
- **THEN** the claim is refused as reserved

#### Scenario: Reserving a name reserves it in both roles at once

- **WHEN** an operator adds a hostname under a wildcard domain to the reserved list
- **THEN** its label immediately stops being claimable as a subdomain, with no second list
  to update

### Requirement: A label already answering as a hostname is refused

A claim MUST be refused when an active deployment already holds the hostname that label
would form under a configured wildcard domain.

#### Scenario: A label held by a live deployment is refused

- **WHEN** an active deployment has the hostname `demo.freepod.eu` and a user claims `demo`
- **THEN** the claim is refused

### Requirement: The account's subdomain is readable

The platform MUST expose the subdomain an account holds, reporting its absence as a value
rather than as an error, so a client can tell "not claimed yet" from "cannot ask".

#### Scenario: An unclaimed account reports no subdomain

- **WHEN** a user holding none reads their subdomain
- **THEN** the response succeeds and reports that none is held

#### Scenario: A claimed account reports its subdomain

- **WHEN** a user holding `adalovelace` reads their subdomain
- **THEN** the response reports `adalovelace` and the fully qualified name it forms

### Requirement: Availability is answerable without authentication

Whether a label is free MUST be answerable by an unauthenticated caller, on the same terms
as the existing hostname check.

Signing up is free and unrestricted, so an authenticated availability check would cost a
round trip and stop nobody; and the answer is public regardless, since every claimed
subdomain appears in certificate transparency logs once its holder deploys anything.

#### Scenario: An anonymous caller can check a label

- **WHEN** an unauthenticated client asks whether a label is available
- **THEN** it receives an answer, with no credential required

#### Scenario: Checking reserves nothing

- **WHEN** a client checks a label and does not claim it
- **THEN** no record is created and the label remains available to anyone
