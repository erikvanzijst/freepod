# cli-handle-required Specification

## Purpose

What the end-user client does when the account it is deploying for holds no handle: it
refuses, says why, and sends the user to the one place the decision is made. It deliberately
doesn't implement the claim a second time.

## Requirements

### Requirement: The client never claims a handle

The client MUST NOT prompt for a handle, validate a candidate, or offer to claim one,
interactively or otherwise. The claim is a one-time, irreversible decision made in the web
interface.

#### Scenario: No prompt is offered

- **WHEN** a deploy is attempted for an account with no handle, with a terminal available
- **THEN** the client asks nothing and claims nothing

#### Scenario: No flag claims one either

- **WHEN** the client's options are examined
- **THEN** none of them submits or reserves a handle

### Requirement: A deploy without a handle stops in preflight

The client MUST read the account's handle from `GET /api/me/handle` during deploy preflight,
before any project archive is packed or any build is created, and MUST stop there when none
is held. It MUST NOT check when updating an existing deployment.

#### Scenario: Nothing is packed or built

- **WHEN** a deploy would create a deployment for an account holding no handle
- **THEN** the client stops before packing, and no archive and no build are created

#### Scenario: An update does not check

- **WHEN** a deploy updates an existing deployment
- **THEN** the client does not stop for want of a handle

### Requirement: The refusal names its cause and directs the user

The refusal MUST state that the account holds no handle, that choosing one is a one-time and
permanent decision, and where in the web interface it is made, using the platform's own
origin for the environment being targeted. It MUST state that nothing was packed, built, or
deployed.

#### Scenario: The refusal is actionable

- **WHEN** the client refuses for want of a handle
- **THEN** it names that cause, gives the web address where the choice is made, and states
  that nothing was built

#### Scenario: The deploy is not resumed

- **WHEN** the user claims a handle in the browser after such a refusal
- **THEN** the client is not waiting, and the user runs the deploy again

#### Scenario: A missing handle is not reported as something else

- **WHEN** a deploy is refused for want of a handle
- **THEN** it is not reported as a declined agreement, an authentication failure, or an
  invalid project

### Requirement: The platform's refusal is recognized by its code

Where the platform refuses a create because no handle is held (the race in which preflight
passed), the client MUST recognize it by the `handle_required` error code, not by its prose,
and report it as the same missing-handle refusal.

#### Scenario: The platform's own refusal is recognized by its code

- **WHEN** the platform rejects a create with the `handle_required` code
- **THEN** the client reports it as a missing handle rather than as a generic bad request

### Requirement: Authentication is never gated on holding a handle

Logging in MUST succeed for an account holding no handle and MUST NOT prompt for one.
Read-only commands MUST work without one.

#### Scenario: Login succeeds without a handle

- **WHEN** a user with no handle logs in
- **THEN** the login succeeds

#### Scenario: Read-only commands are unaffected

- **WHEN** a user with no handle lists products, deployments, or builds
- **THEN** the commands succeed
