# Spec Delta

## MODIFIED Requirements

### Requirement: Added people are invited by email

When the owner adds an entry, the platform SHALL queue one `access.invitation` notification to the added address in the same transaction, with a fixed message: the owner, named by their email address, gave them access to the app at its address, where they sign in with a Freepod account using that email. It SHALL contain no text the owner wrote. Delivery SHALL NOT delay or undo the addition.

#### Scenario: Invitation

- **WHEN** the owner `you@example.com` adds `ana@example.com` to `cloud-yourname.freepod.app`
- **THEN** `ana@example.com` receives one email naming `you@example.com` and `https://cloud-yourname.freepod.app`

#### Scenario: Relay down

- **WHEN** the mail relay is unavailable as the owner adds an entry
- **THEN** the entry is added, and its invitation is queued and ends `failed`

#### Scenario: Addition refused

- **WHEN** an addition is refused, for example because the list is full
- **THEN** no invitation is queued
