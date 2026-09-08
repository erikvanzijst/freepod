## Purpose

What the client does when the account it is deploying for holds no subdomain: refuse, say
why, and send the user to the one place the decision is made. Deliberately not a second
implementation of the claim.

## ADDED Requirements

### Requirement: The client never claims a subdomain

The client MUST NOT prompt for a subdomain, MUST NOT validate a candidate, and MUST NOT
offer to claim one, interactively or otherwise.

The claim is a one-time, irreversible decision whose comprehensibility rests on showing a
whole address and animating the part the user is not choosing. A terminal cannot carry that,
so a prompt here would be a worse version of the screen for the few users who arrive by
this path — and a second implementation of the permanence warning, the confirmation, and the
validation to maintain forever alongside the first.

#### Scenario: No prompt is offered

- **WHEN** a deploy is attempted for an account with no subdomain, with a terminal available
- **THEN** the client asks nothing and claims nothing

#### Scenario: No flag claims one either

- **WHEN** the client's options are examined
- **THEN** none of them submits or reserves a subdomain

### Requirement: A deploy without a subdomain stops in preflight

The client MUST establish that the account holds a subdomain during deploy preflight, before
any project archive is packed or any build is created, and MUST stop there when it does not.

The platform refuses to create the deployment either way; discovering that after packing and
building spends the user's time and a build for a result that was knowable first.

Like acceptance of the terms, this concerns creating a deployment. The client MUST NOT check
it when updating an existing one.

#### Scenario: Nothing is packed or built

- **WHEN** a deploy would create a deployment for an account holding no subdomain
- **THEN** the client stops before packing, and no archive and no build are created

#### Scenario: An update does not check

- **WHEN** a deploy updates an existing deployment
- **THEN** the client does not read the account's subdomain

### Requirement: The refusal names its cause and directs the user

The refusal MUST state that the account holds no address, that choosing one is a one-time
and permanent decision, and where in the web interface it is made. It MUST state that
nothing has been packed, built, or deployed, and MUST NOT report this cause as any other
refusal.

The web address it gives MUST be the platform's own origin, learned from the environment the
client is targeting rather than carried as a constant. The dashboard of an account holding
no subdomain is the invitation, so the origin lands the user where the choice is made
without the client needing to know a path.

Where the platform refuses a create for this reason after preflight has passed — the race in
which a client skips the check — the client MUST recognize it by the `subdomain_required`
error code rather than by matching the refusal's prose.

The deploy is abandoned rather than suspended: holding a packed archive against a decision
being made in another window is worse than costing the user one re-run of a command that is
in their shell history.

#### Scenario: The refusal is actionable

- **WHEN** the client refuses for want of a subdomain
- **THEN** it names that cause, gives the web address where the choice is made, and states
  that nothing was built

#### Scenario: The deploy is not resumed

- **WHEN** the user claims a subdomain in the browser after such a refusal
- **THEN** the client is not waiting, and the user runs the deploy again

#### Scenario: A missing subdomain is not reported as something else

- **WHEN** a deploy is refused for want of a subdomain
- **THEN** it is not reported as a declined agreement, an authentication failure, or an
  invalid project

#### Scenario: The platform's own refusal is recognized by its code

- **WHEN** the platform rejects a create with the `subdomain_required` code
- **THEN** the client reports it as a missing address rather than as a generic bad request

### Requirement: Authentication is never gated on holding a subdomain

Logging in MUST succeed for an account holding no subdomain, and MUST NOT prompt for one.

Authentication also serves automation and read-only use, neither of which a subdomain is a
precondition for — the same reason acceptance of the terms is offered at login but never
required there.

#### Scenario: Login succeeds without a subdomain

- **WHEN** a user with no subdomain logs in
- **THEN** the login succeeds

#### Scenario: Read-only commands are unaffected

- **WHEN** a user with no subdomain lists products, deployments, or builds
- **THEN** the commands succeed
