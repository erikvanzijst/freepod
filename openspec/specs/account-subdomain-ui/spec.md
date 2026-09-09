# account-subdomain-ui Specification

## Purpose

The one-time dialog in which a user chooses the subdomain their account will keep: where it
is reached from, what it has to make understood before the user answers, and how it treats a
decision that cannot be taken back. Mockups and a working prototype of the interaction:
<https://claude.ai/code/artifact/359c879f-7851-47a2-b869-dc25448cc756>

## Requirements

### Requirement: The claim is offered on the dashboard and on deploying

The web interface MUST offer the claim in two places and nowhere else: on the dashboard of
an account holding no subdomain, and on any attempt to deploy from such an account.

On the dashboard it MUST be presented inline, above the dashboard's own content, and MUST
NOT replace or obscure it: an account can hold deployments and no subdomain at once — every
existing account is in exactly that state until the rollout assigns one — and hiding running
applications behind a name picker is a worse first impression than the empty list the
picker was meant to avoid. It MUST NOT be presented as a modal that no one opened.

What makes an empty deployment list tolerable is not that the claim replaces it but that
the deploy action routes through the claim, so nothing on the page is an action that
cannot succeed.

#### Scenario: The claim sits above the dashboard, not in front of it

- **WHEN** a user holding no subdomain opens the dashboard
- **THEN** the claim is presented above the dashboard's content, and the deployment list and
  the application catalog are both still shown

#### Scenario: Deployments are never hidden to ask

- **WHEN** a user holding deployments but no subdomain opens the dashboard
- **THEN** their deployments remain visible

#### Scenario: No modal opens by itself

- **WHEN** the dashboard loads for a user holding no subdomain
- **THEN** no modal is opened

#### Scenario: The field is ready to type into

- **WHEN** the dashboard presents the claim
- **THEN** the field holds focus with its prefill selected, so the name can be replaced
  without reaching for the mouse

A modal that seizes focus on load is an interruption of nothing; an inline field that takes
it is the page offering its one task. The distinction is whether anything was interrupted.

#### Scenario: Deploying without a subdomain opens the dialog first

- **WHEN** a user holding no subdomain acts to deploy a product
- **THEN** the claim opens as a modal instead of the deploy dialog, because the user acted
  and expects to be returned to what they were doing

#### Scenario: A claim leads straight on to deploying

- **WHEN** a user claims a subdomain from the dialog that a deploy action opened
- **THEN** the deploy flow they were entering continues

### Requirement: The invitation is dismissible and the claim is not

The dashboard invitation MUST be dismissible, leaving the rest of the interface usable, and
MUST remain reachable afterwards. Dismissing MUST NOT be recorded as a decision of any kind.

The claim itself is not optional — deploying requires it — but a first-run screen with no way
past it reads as a signup form that lied about being finished, and there is nothing an
account without a subdomain can damage.

#### Scenario: Dismissing leaves a usable interface

- **WHEN** a user dismisses the invitation
- **THEN** it collapses to a single line offering the claim, and the dashboard is otherwise
  unchanged

Dismissal MUST NOT be persisted — not on the server, and not in browser storage. It is
state for the session the user is in, so the invitation returns on a reload. Remembering it
would be recording the decision the requirement above says is not being taken.

#### Scenario: Dismissing is not an answer

- **WHEN** a user dismisses the invitation and later acts to deploy
- **THEN** the claim dialog opens as it would have before

#### Scenario: Dismissal is not remembered

- **WHEN** a user dismisses the invitation and reloads the dashboard
- **THEN** the invitation is presented again, and nothing was written to the server or to
  browser storage

### Requirement: The address is shown whole, with only one part editable

The claim MUST always present the candidate beside the platform domain, with only the user's
own part editable, and MUST constrain the address to a readable measure rather than letting
it stretch to the width of its container — a label at one edge of a wide screen and its
domain at the other is not legible as one name.

Whether an **application label** joins them depends on which question is being asked. On the
deploy path the user is one step from creating an instance, so the whole deployment hostname
is shown. On the dashboard they are choosing the account's own address with no application
in mind, and an application label there answers a question nobody has asked yet.

A bare text field asks for a name whose significance the user cannot see. Showing the domain
alongside it is what makes the question legible: this is a hostname, and you are choosing
one part of it.

#### Scenario: The shape is visible before anything is typed

- **WHEN** the claim is shown
- **THEN** an editable field and the platform domain are shown as one address

#### Scenario: The deploy path shows the whole hostname

- **WHEN** the claim is opened by an attempt to deploy
- **THEN** an application label is shown in front of the address

#### Scenario: The dashboard shows the account's address alone

- **WHEN** the claim is presented on the dashboard
- **THEN** no application label is shown, because no application has been chosen

#### Scenario: Only the user's own part accepts input

- **WHEN** the user interacts with the address
- **THEN** the application label, where shown, and the platform domain are not editable

#### Scenario: The address does not stretch to its container

- **WHEN** the claim is rendered in a container far wider than the address
- **THEN** the address keeps a readable width rather than spanning the container

### Requirement: The application label never rests on a real name

Where an application label is shown, it MUST animate on open — candidate names passing and
decelerating — and MUST come to rest on a placeholder that is not a usable name, never on a
real one. Where none is shown, no animation runs at all.

Resting on a real name asserts two things that are false: that the user chose it, and that it
is now theirs. The placeholder reads `your app`: plain English, and with a space in it so it
cannot be mistaken for a hostname label. It MUST be visually distinguished from the names
that pass, by typeface rather than by any explanatory text, so that the distinction needs
nothing read.

The animation MUST be slow enough that the names approaching rest can be read; a motion that
is only a blur that stops teaches nothing.

#### Scenario: The reel settles on a placeholder

- **WHEN** the opening animation finishes
- **THEN** the application label shows a placeholder rather than any name a user could deploy

#### Scenario: The placeholder is distinguishable without explanation

- **WHEN** the placeholder is at rest beside the user's typed label
- **THEN** it is set differently from both the passing names and the user's own text

#### Scenario: The tail of the animation is legible

- **WHEN** the animation decelerates
- **THEN** the last names before rest are readable rather than blurred

### Requirement: Motion stops, and returns only as feedback

After settling, the application label MUST NOT move on a timer, and MUST NOT move while the
user is typing. It MAY animate once more when a typed label is first found available, and
MUST offer a control to replay the animation on request.

Ambient motion beside a field somebody is typing their name into is an irritation that never
resolves into anything readable; motion tied to an event the user caused is feedback.

#### Scenario: The label is still while the user types

- **WHEN** the user is editing their label
- **THEN** the application label does not move

#### Scenario: Availability is acknowledged with motion

- **WHEN** a typed label is reported available for the first time
- **THEN** the application label may animate once and return to its placeholder

#### Scenario: Reduced motion is honored

- **WHEN** the viewer's system requests reduced motion
- **THEN** no animation runs and the placeholder is shown directly

### Requirement: Availability is checked as the user types

The dialog MUST validate the typed label against the platform as it is typed, debounced, and
MUST show a distinct state for checking, available, and each way a label can be refused. A
refusal MUST name its own cause rather than reporting every rejection as invalid.

It validates by placing the typed label under the platform's wildcard domain and asking the
existing hostname check, which reads a single label at that depth as a subdomain question.
The refusals it can receive are `invalid`, `reserved` and `claimed`; a deployment hostname
is at the other depth and cannot collide with a candidate here, so `in_use` is not among
them.

#### Scenario: Each refusal names its cause

- **WHEN** a label is refused as malformed, as reserved, or as already held
- **THEN** the message distinguishes which of those applies

#### Scenario: An in-flight check is visible

- **WHEN** a check is outstanding
- **THEN** the field shows that it is checking, and the claim action is unavailable

#### Scenario: The claim action follows the check

- **WHEN** the typed label has not been reported available
- **THEN** the claim action is unavailable

### Requirement: The field is prefilled from the user's email address

The dialog MUST open with a candidate derived from the local part of the user's email
address, selected so that typing replaces it. When the derived candidate is unavailable or
malformed, the dialog MUST show it in its refused state rather than silently substituting
another.

The audience is the general population and the shortest path to a working account is the
design goal. The cost is acknowledged rather than mitigated: the prefill nudges people
toward a name derived from their own, which is why the dialog states that the name is
public.

#### Scenario: The prefill is ready to accept or replace

- **WHEN** the dialog opens for a user whose email local part yields an available label
- **THEN** that label is present, selected, and reported available

#### Scenario: An unavailable prefill is shown as refused

- **WHEN** the derived label is already held
- **THEN** it is shown with the refusal that applies, and no substitute is chosen for the user

### Requirement: The dialog states that the choice is permanent and public

Before the user can claim, the dialog MUST state that the address cannot be changed later
and that it is publicly visible, including in certificate transparency logs.

#### Scenario: Both consequences are stated before claiming

- **WHEN** the dialog is shown
- **THEN** its permanence and its public visibility are both stated where the user will read
  them before acting

### Requirement: Claiming passes through a confirmation that shows what is frozen

Claiming MUST require a second, explicit confirmation, presented as its own state of the
dialog with a way back. The confirmation MUST show the full name being frozen — the user's
label and the platform domain together — and MUST NOT show an application label beside it.

The user is freezing one name, so the confirmation shows exactly that name and all of it:
the platform domain is being set in stone alongside the label, and a user who reads only the
emphasized part must still be reading something true. An application label on this screen
implies a second decision is being taken.

Confirmation MUST NOT require the user to retype the name. That ceremony belongs to
destructive actions, and this one creates.

#### Scenario: The confirmation shows the fully qualified name

- **WHEN** the user acts to claim
- **THEN** the dialog shows the label and the platform domain together as the name being
  frozen, with no application label

#### Scenario: The user can go back

- **WHEN** the confirmation is shown
- **THEN** an action returns to the editable state with the typed label intact

#### Scenario: No retyping is demanded

- **WHEN** the confirmation is shown
- **THEN** confirming requires an action, not a transcription of the name

### Requirement: The claimed address is shown in account settings

The account settings page MUST show the subdomain a user holds, and MUST present it as a
fact rather than as an editable field.

#### Scenario: The held address is visible after claiming

- **WHEN** a user holding a subdomain opens account settings
- **THEN** the address is shown, with no control offering to change it
