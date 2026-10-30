# app-access-list Specification

## Purpose
The per-deployment list of people who may sign in to an app whose access is `listed`: who is admitted, how an entry becomes tied to one Freepod account, how owners change the list, and how access is taken back.

## Requirements

### Requirement: A listed deployment admits its owner and its list

When the release a deployment serves has `auth.enabled` and `auth.access: listed`, Sign in with Freepod SHALL admit only the deployment's owner and the people on its access list, whatever the protocol. Anyone else SHALL be refused before any consent page and SHALL receive no identity. With `auth.access: anyone`, the list SHALL have no effect.

#### Scenario: Listed person

- **WHEN** Ana is on the access list of a `listed` deployment and signs in to it
- **THEN** they reach the app

#### Scenario: Stranger

- **WHEN** a Freepod account that is neither the owner nor on the list signs in to a `listed` deployment
- **THEN** it is refused, sees no consent page, and the app receives no identity for it

#### Scenario: List under anyone

- **WHEN** a deployment's serving release has `auth.access: anyone` and its access list still holds entries from an earlier `listed` release
- **THEN** any Freepod account may sign in, as without a list

### Requirement: The owner is always admitted

The deployment's owner SHALL be admitted to a `listed` deployment without being on its list. The owner SHALL NOT be an entry on the list, and no operation on the list SHALL be able to refuse the owner.

#### Scenario: Owner with an empty list

- **WHEN** the owner signs in to a `listed` deployment whose list is empty
- **THEN** the owner reaches the app

#### Scenario: Adding the owner

- **WHEN** the owner asks to add their own email to the list
- **THEN** the request is refused as a duplicate and the list is unchanged

### Requirement: An entry is tied to the first account that uses it

An entry SHALL hold the email the owner added. The first time a Freepod account whose verified email matches it case-insensitively signs in, the entry SHALL be tied to that account's subject. From then on, the entry SHALL admit only that subject, whatever email it signs in with, and SHALL NOT admit another subject with the same email.

#### Scenario: First sign-in binds the entry

- **WHEN** `jules@example.org` is on the list, unbound, and the account with that verified email signs in
- **THEN** it is admitted and the entry records its subject

#### Scenario: Another account with the same address

- **WHEN** an entry is tied to one subject and a different subject with the same verified email signs in
- **THEN** it is refused

#### Scenario: Address changed later

- **WHEN** a person whose entry is tied to their subject changes their Freepod email and signs in again
- **THEN** they are admitted

### Requirement: The owner edits the list through the API

The API SHALL let a deployment's owner read the deployment's access list, add an entry by email, and remove an entry. Platform administrators SHALL be able to read any deployment's list and SHALL NOT be able to change it. Reading SHALL return the whole list in one response.

#### Scenario: Owner adds someone

- **WHEN** the owner adds `ana@example.com` to their deployment's list
- **THEN** the API answers `201` with the new entry, unbound

#### Scenario: Another user

- **WHEN** a user who does not own the deployment reads or changes its list
- **THEN** the API answers as for a deployment that user cannot see

#### Scenario: Administrator reads

- **WHEN** an administrator reads a deployment's list
- **THEN** the API returns it, and an attempt by the administrator to add or remove an entry is refused

### Requirement: Entries are valid and bounded

The API SHALL refuse an entry that is not a syntactically valid email address, one that matches an existing entry or the owner's email case-insensitively, and any addition that would take the list beyond 500 entries. It SHALL store emails in lower case. Additions under concurrency SHALL NOT exceed the bound.

#### Scenario: Duplicate in another case

- **WHEN** `ana@example.com` is on the list and the owner adds `Ana@Example.com`
- **THEN** the API answers `409` and the list is unchanged

#### Scenario: Full list

- **WHEN** a list holds 500 entries and the owner adds another
- **THEN** the API answers `409` and the list is unchanged

#### Scenario: Not an address

- **WHEN** the owner adds `ana@`
- **THEN** the API answers `422`

### Requirement: The list is edited only while it applies

The API SHALL refuse to add an entry to a deployment whose serving release does not have `auth.enabled` and `auth.access: listed`. Removing and reading SHALL work in any mode. A deployment's entries SHALL be kept when its access mode changes, and SHALL apply again if it returns to `listed`.

#### Scenario: Adding under anyone

- **WHEN** the owner adds an entry to a deployment whose serving release has `auth.access: anyone`
- **THEN** the API answers `409`

#### Scenario: Back to listed

- **WHEN** a deployment with entries goes from `listed` to `anyone` and back to `listed`
- **THEN** its earlier entries admit their people again

### Requirement: Changes take effect without a redeploy

Adding or removing an entry SHALL NOT start a reconcile or change any chart value. An addition SHALL admit the person on their next sign-in. A removal SHALL refuse the person within 30 seconds on every request to a `header` app, and at once at the provider's token and userinfo endpoints.

#### Scenario: Removal from a header app

- **WHEN** the owner removes Ana while they have a valid session on a `listed` header app
- **THEN** within 30 seconds their requests no longer reach the app, and no reconcile ran

#### Scenario: Addition takes effect at once

- **WHEN** the owner adds Noor and Noor then opens the `listed` header app and signs in
- **THEN** Noor reaches the app

### Requirement: Removal signs the person out of an OIDC app

When the owner removes an entry tied to a subject from an `oidc` deployment that declares `auth.oidc.backchannelLogoutPath`, the platform SHALL send the app a back-channel logout token for that subject as part of the removal. The entry SHALL be removed only when the app accepts the token; otherwise the removal SHALL fail, naming the app, and the entry SHALL stay. Removing an unbound entry SHALL send nothing.

#### Scenario: Removing a signed-in person

- **WHEN** the owner removes Ana, whose entry is tied to their subject, from a `listed` OIDC app that declares a back-channel logout path
- **THEN** the app receives a logout token for Ana's subject and ends their sessions, and the entry is removed

#### Scenario: App unreachable

- **WHEN** the app cannot be reached, or does not accept the token, when the owner removes Ana
- **THEN** the API answers `502`, and Ana's entry is still on the list

#### Scenario: Unbound entry

- **WHEN** the owner removes an entry nobody has signed in with
- **THEN** no logout token is sent

### Requirement: Added people are invited by email

When the owner adds an entry, the platform SHALL email the added address once, with a fixed message: that the owner, named by their email address, gave them access to the app at its address, and that they sign in there with a Freepod account using that email. The message SHALL contain no text the owner wrote. A failure to send SHALL NOT undo the addition.

#### Scenario: Invitation

- **WHEN** the owner `you@example.com` adds `ana@example.com` to `cloud-yourname.freepod.app`
- **THEN** `ana@example.com` receives one email naming `you@example.com` and `https://cloud-yourname.freepod.app`

#### Scenario: Relay down

- **WHEN** the mail relay is unavailable as the owner adds an entry
- **THEN** the entry is added

### Requirement: Invitations are limited per owner

The API SHALL refuse an addition that would send an owner more than 100 invitations within 24 hours, across all their deployments, with `429` and a message saying when more can be sent. Removing entries SHALL NOT return invitations to the allowance.

#### Scenario: Over the limit

- **WHEN** an owner has sent 100 invitations in the past 24 hours and adds another entry
- **THEN** the API answers `429` and the list is unchanged

#### Scenario: Add and remove does not reset

- **WHEN** an owner adds and removes the same address 100 times within a day and then adds another address
- **THEN** the API answers `429`

### Requirement: Deleting a deployment deletes its list

When a deployment is deleted, its access list SHALL be deleted with it.

#### Scenario: Deleted deployment

- **WHEN** a deployment with entries is deleted
- **THEN** none of its entries remain

### Requirement: Deployments report their authentication settings

The deployment read model SHALL report the serving release's effective `auth.enabled`, `auth.protocol` and `auth.access`, defaults applied, and for a `listed` deployment the number of entries. A deployment with no serving release SHALL report none of these. The report SHALL be computed the same way for every product.

#### Scenario: Listed deployment

- **WHEN** a deployment's serving release has `auth.enabled: true` and `auth.access: listed` and its list holds three entries
- **THEN** its read model reports enabled, `header`, `listed` and three entries

#### Scenario: Defaults

- **WHEN** a deployment's serving release sets only `auth.enabled: true`
- **THEN** its read model reports `header` and `anyone`
