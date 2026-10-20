# account-handle Specification

## Purpose

The handle an account holds: one short name, claimed once and never changed or released,
that ends the hostname of everything the account deploys (`<app>-<handle>.<tenant domain>`).
Recorded on the user and claimed through its own resource.

## Requirements

### Requirement: An account holds at most one handle

The user MUST carry a nullable `handle` column, NULL until claimed. At most one user MUST
hold any given handle, enforced by a unique index over the lowercased value rather than by
the code that writes it. The stored value MUST be lowercase; a mixed-case claim MUST be
normalized before it is checked or stored.

#### Scenario: A new account holds no handle

- **WHEN** a user record is created
- **THEN** its handle is NULL

#### Scenario: Two accounts cannot hold one handle

- **WHEN** a claim is written for a handle another user already holds
- **THEN** the write is refused by the database

#### Scenario: Case does not create a second handle

- **WHEN** a user claims `Alice` and another user later claims `alice`
- **THEN** the first is stored as `alice` and the second is refused as `handle_taken`

### Requirement: A handle is claimed once and never changes

`POST /api/me/handle` MUST store the submitted handle for an account holding none. For an
account that already holds a handle, a claim for that same handle MUST succeed with **200**
and change nothing, and a claim for any other handle MUST be refused with **409**.

The platform MUST NOT provide any interface for changing or releasing a handle: no endpoint,
no CLI command, no administrative action.

#### Scenario: A first claim is accepted

- **WHEN** a user holding no handle claims an available one
- **THEN** it is stored on their record and the response reports it

#### Scenario: Re-claiming the held handle is idempotent

- **WHEN** a user holding `alice` claims `alice`
- **THEN** the API responds **200**, reports `alice`, and writes nothing

#### Scenario: A different handle is refused

- **WHEN** a user holding `alice` claims `bob`
- **THEN** the API responds **409** `handle_already_claimed` and the held handle is unchanged

#### Scenario: No interface releases a handle

- **WHEN** the API surface, the operator CLI and the administrative interface are examined
- **THEN** none of them offers to change, clear, or transfer an account's handle

### Requirement: A dry run answers exactly as the claim would

`POST /api/me/handle?dry_run=1` MUST run every check a real claim runs and return the
response a real claim would, but MUST NOT store or reserve anything. It is the way a client
learns whether a handle is available before claiming it.

#### Scenario: An available handle

- **WHEN** a user holding no handle dry-runs a claim for an available one
- **THEN** the API responds as a successful claim would, and the user still holds no handle

#### Scenario: A refused handle

- **WHEN** a user dry-runs a claim for a handle that is malformed, reserved, or held by
  another account
- **THEN** the API refuses it with the same status and reason a real claim would receive

#### Scenario: The held handle

- **WHEN** a user holding `alice` dry-runs a claim for `alice`
- **THEN** the API responds **200**

#### Scenario: Nothing is reserved

- **WHEN** two users dry-run the same available handle
- **THEN** both are told it is available, and either may claim it

### Requirement: Refusals carry a machine-readable code

Every refused claim or dry run MUST carry a stable error code, so a client can tell the user
which cause applies without matching prose: **400** `handle_invalid` (malformed), **400**
`handle_reserved` (reserved), **409** `handle_taken` (another account holds it), and **409**
`handle_already_claimed` (this account holds a different one).

#### Scenario: Each refusal names its cause

- **WHEN** a claim is refused because the handle is malformed, reserved, held by another
  account, or differs from the one this account holds
- **THEN** the response carries `handle_invalid`, `handle_reserved`, `handle_taken`, or
  `handle_already_claimed` respectively

### Requirement: The operator CLI claims, and only claims

The `caelus` CLI MUST offer a claim mirroring `POST /api/me/handle`, so an operator can
settle the precondition deployment create enforces. It MUST NOT offer to change, clear, or
transfer a handle.

#### Scenario: The operator can settle the precondition

- **WHEN** an operator claims a handle for a user through the CLI and then creates a
  deployment for them
- **THEN** both succeed

#### Scenario: The CLI offers no way back

- **WHEN** the CLI's commands are examined
- **THEN** none of them changes, clears, or transfers a handle

### Requirement: A deleted account does not release its handle

A handle MUST remain held when its account is deleted and MUST NOT become claimable by
another account. A released handle would inherit the previous holder's links and bookmarks.

#### Scenario: A deleted account's handle stays unavailable

- **WHEN** an account holding `alice` is deleted and another user claims `alice`
- **THEN** the claim is refused as `handle_taken`

### Requirement: A handle is 2 to 20 lowercase letters and digits

A handle MUST be 2 to 20 characters of `[a-z0-9]`, and anything else MUST be refused as
`handle_invalid`. It MUST NOT contain `-`, so that it is always the last `-`-separated segment of a
tenant hostname label. Twenty characters keeps the longest tenant label within 63.

#### Scenario: A well-formed handle is accepted

- **WHEN** a user claims `adalovelace`
- **THEN** the format check passes

#### Scenario: A dash is refused

- **WHEN** a user claims `ada-lovelace`
- **THEN** the claim is refused as `handle_invalid`

#### Scenario: A dot or other character is refused

- **WHEN** a user claims `ada.lovelace` or `ada_lovelace`
- **THEN** the claim is refused as `handle_invalid`

#### Scenario: A handle outside the length bounds is refused

- **WHEN** a user claims a single character, or a value longer than 20 characters
- **THEN** the claim is refused as `handle_invalid`

### Requirement: Reserved handles are refused

A claim MUST be refused as `handle_reserved` when the handle appears in the platform's list of
reserved handles. The list MUST be the same in every environment, and MUST include the
names of the platform's own services and names that would read as Freepod's own, such as
`freepod`, `admin`, `support`, `security`, `billing` and `official`.

#### Scenario: A platform name is refused

- **WHEN** `www` is a reserved handle and a user claims `www`
- **THEN** the claim is refused as `handle_reserved`

#### Scenario: One list for every environment

- **WHEN** a handle is reserved
- **THEN** it is refused in production and in development alike

### Requirement: The account's handle is readable

`GET /api/me/handle` MUST always succeed for an authenticated caller and report `handle`
(null until claimed), `suffix` and `domain`. `suffix` MUST be the exact text that follows an
application label in this account's hostnames (`-<handle>.<tenant domain>`), null until a
handle is claimed. `domain` MUST be the tenant domain, reported whether or not a handle is
held.

#### Scenario: An unclaimed account reports no handle

- **WHEN** a user holding none reads their handle on a platform whose tenant domain is
  `freepod.app`
- **THEN** the response succeeds with `handle` and `suffix` null and `domain` `freepod.app`

#### Scenario: A claimed account reports its handle and suffix

- **WHEN** a user holding `adalovelace` reads their handle on a platform whose tenant domain
  is `freepod.app`
- **THEN** the response reports `adalovelace`, `-adalovelace.freepod.app`, and `freepod.app`
