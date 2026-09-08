## ADDED Requirements

### Requirement: Deployment create requires a claimed subdomain

Deployment create MUST NOT carry any subdomain field, for either REST
`POST /users/{user_id}/deployments` or the equivalent CLI command. Instead it MUST require
that the owning user already holds a subdomain (claimed via `POST /api/me/subdomain`). A
create for a user holding none MUST be rejected with a client error (**400**) and MUST NOT
create a deployment. The guard MUST be enforced server-side, so the claim-then-deploy flow
cannot be bypassed by a direct API or CLI client, exactly as the Terms of Service
precondition is.

The rejection MUST carry the stable error code `subdomain_required`, so a client
distinguishes it from the Terms of Service rejection by an identifier rather than by
matching prose.

The precondition is enforced at creation and not at authentication: an account with no
subdomain can sign in, read, and use every part of the platform that does not create a
deployment.

#### Scenario: Deploy after claiming succeeds

- **WHEN** a user holding a subdomain creates a deployment with an otherwise valid payload
- **THEN** the API creates the deployment, and its payload and response contain no subdomain
  field

#### Scenario: Deploy without a subdomain is rejected

- **WHEN** a user holding no subdomain attempts to create a deployment
- **THEN** the API responds **400** with code `subdomain_required` and no deployment is
  created

#### Scenario: CLI deploy without a subdomain is rejected

- **WHEN** an operator runs the CLI create-deployment command for a user holding none
- **THEN** the command fails without creating a deployment

#### Scenario: Updating an existing deployment does not check

- **WHEN** a deployment that already exists is updated
- **THEN** the subdomain precondition is not applied

#### Scenario: The two preconditions are reported separately

- **WHEN** a user has neither accepted the Terms nor claimed a subdomain
- **THEN** the rejection identifies which precondition failed by its own error code rather
  than reporting one as the other

### Requirement: A deployment hostname sits beneath its own owner's subdomain

When a deployment's hostname falls under a configured wildcard domain, the account subdomain
in it MUST be the one the owning user holds. A create naming another account's subdomain
MUST be rejected and MUST NOT create a deployment. The check MUST run wherever the owner is
known — at deployment create — because the hostname validator is given a name and a session
and has no notion of an owner.

Without it, one account can address an application beneath another's name: the traffic, the
links and the certificate all say the name belongs to somebody who did not deploy it.

Hostnames outside every configured wildcard domain are the user's own DNS and are not
subject to this rule; they remain governed by the CNAME check.

#### Scenario: A deployment beneath the owner's own subdomain is accepted

- **WHEN** a user holding `alice` creates a deployment with hostname `photos.alice.freepod.eu`
- **THEN** the create proceeds

#### Scenario: A deployment beneath another account's subdomain is refused

- **WHEN** a user holding `bob` creates a deployment with hostname `photos.alice.freepod.eu`
- **THEN** the create is rejected and no deployment is created

#### Scenario: A custom domain is unaffected

- **WHEN** a user creates a deployment with hostname `photos.example.com` and `example.com`
  is not a configured wildcard domain
- **THEN** the ownership rule does not apply
