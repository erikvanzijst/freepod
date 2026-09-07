## REMOVED Requirements

### Requirement: Email verification is required

**Reason**: The requirement fused two claims — that the realm verifies email addresses, and
that the email claim is the sole join key to Freepod's user records, with no Keycloak
subject identifier persisted anywhere. The second is no longer true. Left fused, the
surviving half would read as though it were justified by the retired one, and the scenario
asserting that no subject is persisted would contradict the platform's actual behavior.

**Migration**: Replaced by "Email verification gates record adoption" below. Email
verification is NOT being relaxed: `verifyEmail` stays `true` and the realm continues to
refuse duplicate addresses. Only the stated reason changes, from "email is the identity" to
"a verified address is what claims a record that carries no subject yet".

## ADDED Requirements

### Requirement: Email verification gates record adoption

The system SHALL require email verification for new user accounts in the `freepod` realm,
and SHALL NOT relax it.

Freepod resolves an authenticated caller to its own user record by the Keycloak subject,
not by email. Verification remains a security control for a narrower but still load-bearing
reason: a record that carries no subject yet is claimed by the caller whose email matches
it, so an account whose address could be set to somebody else's would take over that
Freepod record on its first authenticated request. Together with the realm refusing to let
two accounts hold one address, verification is what makes that claim safe.

#### Scenario: Email verification is required
- **WHEN** the `freepod` realm settings are inspected
- **THEN** `verifyEmail` is set to `true`

#### Scenario: The subject is the identity join key
- **WHEN** Freepod resolves an authenticated caller to a user record
- **THEN** the lookup is performed on the Keycloak subject
- **AND** the subject is persisted on the record it resolves to

#### Scenario: A verified address claims a record that has no subject
- **WHEN** an authenticated caller's subject matches no record and their verified email
  matches a record carrying no subject
- **THEN** that record is claimed by the caller's subject
- **AND** it is thereafter reachable by subject alone

### Requirement: Clients issue a public subject identifier

Every client in the `freepod` realm through which an end user authenticates to Freepod
SHALL issue the same subject for a given user — that is, the realm's default public subject
type, not a pairwise one.

A pairwise subject is derived per client. Freepod is reached through more than one client
per environment (a browser session client and a CLI client), so a pairwise subject would
give one person a different identifier depending on how they connected, and the platform
would resolve them to a different account for each. The failure is silent and looks to the
user like the CLI and the web interface disagreeing about what they own.

#### Scenario: Subject type is public on every Freepod client
- **WHEN** the environment session clients and CLI clients are inspected
- **THEN** none is configured to issue a pairwise subject

#### Scenario: One identity presents one subject across clients
- **WHEN** the same user authenticates through the browser client and through the CLI client
  of one environment
- **THEN** the subject in both tokens is identical
