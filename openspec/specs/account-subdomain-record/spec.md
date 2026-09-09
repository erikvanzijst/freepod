# account-subdomain-record Specification

## Purpose

The subdomain an account holds: one DNS label, claimed once, never changed and never
released, under which everything that account deploys is addressed. Recorded on the
user beside the other user-level facts, and claimed through its own resource rather than as
a field on anything else.

## Requirements

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

### Requirement: The operator CLI claims, and only claims

The `caelus` CLI MUST offer a claim mirroring `POST /api/me/subdomain`, so the
operator tool can settle the precondition it enforces. It MUST NOT offer to
change, clear, or transfer one.

Without it `caelus create-deployment` cannot succeed for any account, which
would break the parity between REST and the operator CLI that this codebase
keeps deliberately. It is also what assigns subdomains during the rollout.

#### Scenario: The operator can settle the precondition

- **WHEN** an operator claims a subdomain for a user through the CLI and then
  creates a deployment for them
- **THEN** both succeed

#### Scenario: The CLI offers no way back

- **WHEN** the CLI's commands are examined
- **THEN** none of them changes, clears, or transfers a subdomain

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

A claim MUST be refused unless the submitted value is one label: **2 to 63 characters** of
lowercase alphanumerics and hyphens, beginning and ending with an alphanumeric. A value
containing a dot MUST be refused — an account claims a label, not a name.

63 is the limit RFC 1035 places on a DNS label, which the platform's own hostname format
check already enforces; a longer value would be stored and then refused by every hostname
derived from it, and could not be certificated. The minimum of 2 reserves single-character
labels for the platform.

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

#### Scenario: A label outside the length bounds is refused

- **WHEN** a user claims a single character, or a value longer than 63 characters
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

### Requirement: The account's subdomain is readable

The platform MUST expose the subdomain an account holds, reporting its absence as a value
rather than as an error, so a client can tell "not claimed yet" from "cannot ask".

The fully qualified name it reports MUST be `<label>.<platform domain>` — the name that
actually receives a DNS record and a wildcard certificate — so that what a client displays
and what the reconciler provisions cannot diverge.

It MUST also report the platform domain on its own, whether or not a subdomain is held. A
client offering the claim has to render the suffix before there is a label to compose it
with, and that suffix is not otherwise discoverable: it is the platform's own domain, not
one of a list to choose from.

#### Scenario: An unclaimed account reports no subdomain

- **WHEN** a user holding none reads their subdomain
- **THEN** the response succeeds and reports that none is held

#### Scenario: A claimed account reports its subdomain

- **WHEN** a user holding `adalovelace` reads their subdomain on a platform whose domain is
  `freepod.eu`
- **THEN** the response reports `adalovelace`, `adalovelace.freepod.eu`, and `freepod.eu`

#### Scenario: An unclaimed account still learns the suffix

- **WHEN** a user holding no subdomain reads their subdomain
- **THEN** the response reports the platform domain, so the claim can render the address it
  is offering

### Requirement: Availability is answered by the existing hostname check

Whether a label is free MUST be answerable before it is claimed, through
`GET /api/hostnames/{fqdn}` with the candidate placed under a configured wildcard domain,
rather than through a second endpoint of its own.

One label under a wildcard domain is a subdomain and two are an application, so the existing
checker can answer both questions from the name it is given. A dedicated availability
endpoint would be a second public surface answering a question the first one already holds
all the state for.

Checking MUST reserve nothing: the answer is advisory, and two clients can be told the same
label is free.

#### Scenario: A label is checked before claiming

- **WHEN** a client checks `alice.freepod.eu` and `freepod.eu` is a configured wildcard domain
- **THEN** it receives an answer about the subdomain `alice`, not about a deployment

#### Scenario: Checking reserves nothing

- **WHEN** a client checks a label and does not claim it
- **THEN** no record is created and the label remains available to anyone
