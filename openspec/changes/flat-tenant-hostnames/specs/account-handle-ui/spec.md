# Spec Delta

## Purpose

The one-time dialog in which a user chooses the handle their account will keep: where it is
reached from, what it makes understood before the user answers, and how it treats a decision
that cannot be taken back.

## ADDED Requirements

### Requirement: The claim is offered on the dashboard and on deploying

The web interface MUST offer the claim in two places and nowhere else: inline above the
dashboard of an account holding no handle, and on any attempt to deploy from such an
account. On the dashboard it MUST NOT replace or obscure the dashboard's content and MUST
NOT open as a modal no one asked for.

#### Scenario: The claim sits above the dashboard, not in front of it

- **WHEN** a user holding no handle opens the dashboard
- **THEN** the claim is presented above the dashboard's content, and the deployment list and
  the application catalog are both still shown

#### Scenario: Deployments are never hidden to ask

- **WHEN** a user holding deployments but no handle opens the dashboard
- **THEN** their deployments remain visible

#### Scenario: No modal opens by itself

- **WHEN** the dashboard loads for a user holding no handle
- **THEN** no modal is opened

#### Scenario: The field is ready to type into

- **WHEN** the dashboard presents the claim
- **THEN** the field holds focus with its prefill selected, so the name can be replaced
  without reaching for the mouse

#### Scenario: Deploying without a handle opens the dialog first

- **WHEN** a user holding no handle acts to deploy a product
- **THEN** the claim opens as a modal instead of the deploy dialog

#### Scenario: A claim leads straight on to deploying

- **WHEN** a user claims a handle from the dialog that a deploy action opened
- **THEN** the deploy flow they were entering continues

### Requirement: The invitation is dismissible and the claim is not

The dashboard invitation MUST be dismissible, leaving the rest of the interface usable, and
MUST remain reachable afterwards. Dismissal MUST NOT be recorded as a decision, and MUST NOT
be persisted on the server or in browser storage: it lasts for the session the user is in.

#### Scenario: Dismissing leaves a usable interface

- **WHEN** a user dismisses the invitation
- **THEN** it collapses to a single line offering the claim, and the dashboard is otherwise
  unchanged

#### Scenario: Dismissing is not an answer

- **WHEN** a user dismisses the invitation and later acts to deploy
- **THEN** the claim dialog opens as it would have before

#### Scenario: Dismissal is not remembered

- **WHEN** a user dismisses the invitation and reloads the dashboard
- **THEN** the invitation is presented again, and nothing was written to the server or to
  browser storage

### Requirement: The address is shown whole, with only the handle editable

The claim MUST present the handle field inside the address it completes, with the tenant
domain after it and only the handle editable, and MUST keep the address to a readable width.
On the deploy path an application label and its `-` separator precede the field, showing
`<app>-<handle>.<tenant domain>`. On the dashboard the address is shown without an
application label.

#### Scenario: The shape is visible before anything is typed

- **WHEN** the claim is shown
- **THEN** an editable field and the tenant domain are shown as one address

#### Scenario: The deploy path shows the whole hostname

- **WHEN** the claim is opened by an attempt to deploy on a platform whose tenant domain is
  `freepod.app`
- **THEN** the address reads as an application label, `-`, the editable handle, and
  `.freepod.app`

#### Scenario: The dashboard shows the account's address alone

- **WHEN** the claim is presented on the dashboard
- **THEN** no application label is shown, because no application has been chosen

#### Scenario: Only the handle accepts input

- **WHEN** the user interacts with the address
- **THEN** the application label, where shown, and the tenant domain are not editable

#### Scenario: The address does not stretch to its container

- **WHEN** the claim is rendered in a container far wider than the address
- **THEN** the address keeps a readable width rather than spanning the container

### Requirement: The application label never rests on a real name

Where an application label is shown, it MUST animate on open, with candidate names passing and
decelerating, and MUST come to rest on the placeholder `your app`, never on a real name. The
placeholder MUST be set in a different typeface from the passing names. Where no label is
shown, no animation runs. The deceleration MUST be slow enough to read.

#### Scenario: The reel settles on a placeholder

- **WHEN** the opening animation finishes
- **THEN** the application label shows a placeholder rather than any name a user could deploy

#### Scenario: The placeholder is distinguishable without explanation

- **WHEN** the placeholder is at rest beside the user's typed handle
- **THEN** it is set differently from both the passing names and the user's own text

#### Scenario: The tail of the animation is legible

- **WHEN** the animation decelerates
- **THEN** the last names before rest are readable rather than blurred

### Requirement: Motion stops, and returns only as feedback

After settling, the application label MUST NOT move on a timer or while the user is typing.
It MAY animate once more when a typed handle is first found available, and MUST offer a
control to replay the animation. Under a reduced-motion preference no animation runs.

#### Scenario: The label is still while the user types

- **WHEN** the user is editing their handle
- **THEN** the application label does not move

#### Scenario: Availability is acknowledged with motion

- **WHEN** a typed handle is reported available for the first time
- **THEN** the application label may animate once and return to its placeholder

#### Scenario: Reduced motion is honored

- **WHEN** the viewer's system requests reduced motion
- **THEN** no animation runs and the placeholder is shown directly

### Requirement: Availability is checked as the user types

The dialog MUST check the typed handle as it is typed, debounced, through a dry-run claim
(`POST /api/me/handle?dry_run=1`), and MUST show a distinct state for checking, available,
and each refusal (`handle_invalid`, `handle_reserved`, `handle_taken`), naming its cause.

#### Scenario: The check is a dry-run claim

- **WHEN** the user pauses after typing `alice`
- **THEN** the dialog sends a dry-run claim for `alice`, and nothing is stored

#### Scenario: Each refusal names its cause

- **WHEN** a handle is refused as malformed, as reserved, or as already held
- **THEN** the message distinguishes which of those applies

#### Scenario: Disallowed characters are explained

- **WHEN** the user types a `-` or any character outside letters and digits
- **THEN** the refusal says that a handle is letters and digits only

#### Scenario: An in-flight check is visible

- **WHEN** a check is outstanding
- **THEN** the field shows that it is checking, and the claim action is unavailable

#### Scenario: The claim action follows the check

- **WHEN** the typed handle has not been reported available
- **THEN** the claim action is unavailable

### Requirement: The field is prefilled from the user's email address

The dialog MUST open with a candidate derived from the local part of the user's email
address, reduced to letters and digits, truncated to the handle's maximum length and selected
so that typing replaces it. When that candidate is unavailable or malformed, the dialog MUST
show it as refused rather than silently substituting another.

#### Scenario: The prefill is ready to accept or replace

- **WHEN** the dialog opens for `ada.lovelace@example.com` and `adalovelace` is available
- **THEN** `adalovelace` is present, selected, and reported available

#### Scenario: An unavailable prefill is shown as refused

- **WHEN** the derived handle is already held
- **THEN** it is shown with the refusal that applies, and no substitute is chosen for the user

### Requirement: The dialog states that the choice is permanent and public

Before the user can claim, the dialog MUST state that the handle cannot be changed later and
that it is publicly visible as part of every address the account's applications are served
at.

#### Scenario: Both consequences are stated before claiming

- **WHEN** the dialog is shown
- **THEN** its permanence and its public visibility are both stated where the user will read
  them before acting

### Requirement: Claiming passes through a confirmation that shows what is frozen

Claiming MUST require a second, explicit confirmation, shown as its own state of the dialog
with a way back. The confirmation MUST show the handle within the address shape it fixes,
`-<handle>.<tenant domain>`, with no application label. It MUST NOT require retyping the
handle.

#### Scenario: The confirmation shows the handle in its address

- **WHEN** the user acts to claim `alice` on a platform whose tenant domain is `freepod.app`
- **THEN** the dialog shows `-alice.freepod.app` as what is being frozen, with no application
  label

#### Scenario: The user can go back

- **WHEN** the confirmation is shown
- **THEN** an action returns to the editable state with the typed handle intact

#### Scenario: No retyping is demanded

- **WHEN** the confirmation is shown
- **THEN** confirming requires an action, not a transcription of the handle

### Requirement: The claimed handle is shown in account settings

The account settings page MUST show the handle a user holds and the address suffix it gives
their applications, as a fact rather than as an editable field.

#### Scenario: The held handle is visible after claiming

- **WHEN** a user holding a handle opens account settings
- **THEN** the handle and its suffix are shown, with no control offering to change them
