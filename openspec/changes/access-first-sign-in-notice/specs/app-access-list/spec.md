# Spec Delta

## ADDED Requirements

### Requirement: The owner learns when someone first signs in

When an entry is first tied to the account that signs in with it, the platform SHALL queue one `access.first_sign_in` notification to the deployment's owner, as a Freepod user. It SHALL name the entry's email and the app's address, and say that the app may now know the person. It SHALL contain no text the person or the owner wrote. Each entry SHALL cause at most one such notification.

#### Scenario: First sign-in

- **WHEN** `ana@example.com` is on the list of `cloud-yourname.freepod.app`, unbound, and signs in to it for the first time
- **THEN** the owner receives one email naming `ana@example.com` and `https://cloud-yourname.freepod.app`

#### Scenario: Later sign-ins

- **WHEN** Ana, whose entry is already tied to their subject, signs in again
- **THEN** no notification is queued

#### Scenario: Two sign-ins at once

- **WHEN** Ana's first sign-in arrives twice at the same moment
- **THEN** one notification is queued

#### Scenario: Removed and added again

- **WHEN** the owner removes Ana's bound entry, adds `ana@example.com` again, and Ana signs in
- **THEN** the owner is notified again

#### Scenario: The owner signs in

- **WHEN** the owner signs in to their own `listed` deployment
- **THEN** no notification is queued

#### Scenario: Refused sign-in

- **WHEN** an account that is not on the list is refused
- **THEN** no notification is queued

### Requirement: A lost notice does not refuse the sign-in

If the first sign-in notice cannot be queued, the entry SHALL still be tied to the subject and the person SHALL still be admitted.

#### Scenario: Outbox refuses the notice

- **WHEN** the database refuses to queue the notice as Ana's entry is bound
- **THEN** Ana is admitted, their entry is bound, and no notice is queued
