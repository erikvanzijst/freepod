## Purpose

How an authenticated request becomes a Freepod user record: which identity claim is the
join key, how records that predate that key are adopted, and what happens when the address
a person authenticates with changes. The identity a caller presents is issued by Keycloak
and outlives every attribute on it; the record it resolves to must outlive them too.

## ADDED Requirements

### Requirement: The Keycloak subject is the join key

The platform MUST resolve an authenticated caller to a user record by the subject
identifier Keycloak issued for that identity, and MUST persist that subject on the record
it resolves to. The subject MUST be treated as an opaque string: the platform MUST NOT
parse it, derive anything from it, or require it to take any particular form.

Email MUST NOT be the identity of a record. It remains an attribute the record carries, and
a mutable one — a person may change the address they authenticate with, and doing so MUST
NOT change which record they resolve to.

Resolution MUST be attempted in this order, and MUST stop at the first match: the record
carrying the presented subject; then a record carrying no subject whose email matches; then
no record, in which case one is created. A record carrying a subject MUST NOT be matched by
email under any circumstances, so that once a record has been bound to an identity, no
other identity can reach it by presenting an address.

#### Scenario: A returning caller resolves by subject

- **WHEN** a request presents a subject that a user record already carries
- **THEN** it resolves to that record
- **AND** the record's email is not part of the match

#### Scenario: The subject is opaque

- **WHEN** the platform receives a subject in any form Keycloak may issue
- **THEN** it is stored and compared as an opaque string
- **AND** no behavior depends on its internal structure

#### Scenario: A bound record is unreachable by email

- **WHEN** a request presents a subject that matches no record, and an email address that
  matches a record already carrying a different subject
- **THEN** the request does not resolve to that record
- **AND** a new record is created instead

### Requirement: A record that carries no subject is adopted by email

The platform MUST adopt a user record that carries no subject when the caller's email
matches it, binding the presented subject to that record permanently. Adoption MUST be the
only circumstance in which an email match resolves a caller, and each record MUST be
adoptable only once.

This is what carries accounts created before subjects were recorded across to the new join
key without a migration: each one is adopted the first time its owner authenticates, and
from that moment is reachable only by subject.

Adoption is safe only because the realm verifies email addresses and permits no two
accounts to hold one simultaneously: the caller has proven control of the address that
names the record. The same reasoning already justifies email verification, so adoption
MUST NOT be extended to unverified addresses.

#### Scenario: A pre-existing record is adopted on first authenticated request

- **WHEN** a caller whose record carries no subject makes an authenticated request
- **THEN** the request resolves to that record
- **AND** the presented subject is stored on it

#### Scenario: An adopted record is thereafter reached by subject alone

- **WHEN** a record has been adopted and the same caller returns with a changed email
  address
- **THEN** it still resolves to that record

#### Scenario: Adoption requires no operator action

- **WHEN** the platform is deployed with records that carry no subject
- **THEN** those records are adopted as their owners authenticate
- **AND** no sweep, backfill, or maintenance window is required for them to keep working

### Requirement: A changed email address updates the record rather than creating one

When a request resolves by subject to a record whose stored email differs from the one the
request presents, the platform MUST update the record's email to the presented value. It
MUST NOT create a second record, and MUST NOT leave the caller's deployments, keys,
acceptances or subscription behind on the record it resolved to.

An address change is the failure this capability exists to prevent: everything a user owns
hangs off the record, and a record they can no longer reach is indistinguishable to them
from one that has been emptied.

#### Scenario: An address change keeps the account

- **WHEN** a user changes the email address on their Keycloak account and makes an
  authenticated request
- **THEN** the request resolves to their existing record
- **AND** the record's email is updated to the new address
- **AND** everything the record owns remains attached to it

#### Scenario: No second record is created by an address change

- **WHEN** a user has changed their address and returns
- **THEN** the platform holds exactly one record for that subject

### Requirement: An unknown caller is recorded with both identifiers

When neither the presented subject nor an adoptable email matches any record, the platform
MUST create one carrying both the subject and the email, so that the record is bound to the
identity from its first request and never enters the adoptable state.

#### Scenario: A new account is bound on creation

- **WHEN** a caller the platform has never seen makes an authenticated request
- **THEN** a record is created carrying the presented subject and email

#### Scenario: A newly created record is not adoptable

- **WHEN** a record has been created for a caller
- **THEN** no other identity can reach it by presenting its email address

### Requirement: A request that presents no subject resolves by email alone

The platform MUST resolve a request that carries an email but no subject by email alone,
MUST NOT reject it, and MUST NOT record a subject as a result of it. Not every context that
authenticates a caller supplies a subject, and a platform that failed closed on its absence
would be unusable in those contexts while adding no protection in the ones that do supply
it.

#### Scenario: A request without a subject still resolves

- **WHEN** a request carries an email address and no subject
- **THEN** it resolves to the record for that address, creating one if none exists

#### Scenario: A missing subject does not unbind a record

- **WHEN** a request without a subject resolves to a record that carries one
- **THEN** the record's subject is left unchanged

#### Scenario: A missing subject does not bind a record

- **WHEN** a request without a subject resolves to a record that carries none
- **THEN** the record remains adoptable

### Requirement: One active record per subject

The platform MUST hold at most one non-deleted user record for any subject, enforced by the
store rather than by the code that writes it, matching the guarantee the email column
already carries.

#### Scenario: A duplicate subject is refused by the store

- **WHEN** a second non-deleted record is written with a subject an existing non-deleted
  record already carries
- **THEN** the write is refused

#### Scenario: A deleted record does not reserve its subject

- **WHEN** a record has been deleted and the same subject authenticates again
- **THEN** a new record is created
- **AND** the deleted record is neither resolved nor adopted

### Requirement: Adoption remains available permanently

The platform MUST retain adoption by email indefinitely, and MUST NOT treat it as a
migration step to be deleted once every record carries a subject.

Subjects are scoped to the realm that issued them: replacing or rebuilding a realm reissues
every subject in it at once, and every record then carries one that corresponds to no
identity. Recovering from that MUST be an operator clearing the stored subjects — after
which the population is adoptable again and re-binds as people authenticate — and MUST NOT
be achieved by relaxing the rule that a record carrying a subject is never matched by
email. That rule is the whole of the protection; a platform that softened it to cope with a
realm replacement would be reachable by address for every account, permanently, to solve a
problem that arises approximately never.

#### Scenario: A cleared subject makes a record adoptable again

- **WHEN** an operator clears the stored subject on a record whose subject no longer
  corresponds to any identity
- **THEN** the record is adopted, by the rules above, the next time its owner authenticates

#### Scenario: A stale subject is not worked around by matching email

- **WHEN** a record carries a subject that corresponds to no identity, and its owner
  authenticates with a newly issued subject and the same email address
- **THEN** the platform does not match that record by email
- **AND** recovering the record requires the operator action above
