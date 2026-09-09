# deployment-create-contract Specification

## Purpose
Defines the contract for creating and updating a deployment: which fields the
API and CLI accept and return, how the hostname is derived from the template
schema rather than supplied by the client, how vars are accepted as write-only
input, and the preconditions — ToS acceptance, and checkout for paid plans —
that a create must satisfy.

## Requirements
### Requirement: Deployment write contracts exclude hostname across API and CLI
The system MUST define deployment write inputs without a top-level `hostname` field for REST API `POST /deployments`, REST API `PUT /deployments`, and equivalent CLI create/update commands.

#### Scenario: Valid create request without hostname
- **WHEN** a client sends a `POST /deployments` request containing only supported fields
- **THEN** the API accepts the request and processes deployment creation

#### Scenario: Create payload includes hostname field
- **WHEN** a client sends a `POST /deployments` request containing `hostname`
- **THEN** the API rejects the request with a client validation error indicating unsupported input

#### Scenario: Update payload includes hostname field
- **WHEN** a client sends a `PUT /deployments` request containing `hostname`
- **THEN** the API rejects the request with a client validation error indicating unsupported input

#### Scenario: CLI create input includes hostname field
- **WHEN** a user runs the CLI create-deployment command with a `hostname` option/argument
- **THEN** the CLI rejects the input and does not invoke deployment creation

#### Scenario: CLI update input includes hostname field
- **WHEN** a user runs the CLI update-deployment command with a `hostname` option/argument
- **THEN** the CLI rejects the input and does not invoke deployment update

### Requirement: Deployment reads return hostname
The system MUST include `hostname` (renamed from `domainname`) in deployment read responses, including `GET /deployment` responses.

#### Scenario: Read deployment returns hostname field
- **WHEN** a client retrieves a deployment using the read endpoint
- **THEN** the response includes the `hostname` field (not `domainname`)

### Requirement: Deployment reads return name and namespace
The system MUST include `name` and `namespace` in deployment read responses. The field `deployment_uid` MUST NOT appear in API responses.

#### Scenario: Read deployment returns name and namespace fields
- **WHEN** a client retrieves a deployment using the read endpoint
- **THEN** the response includes the `name` field and the `namespace` field
- **AND** the response does NOT include a `deployment_uid` field

### Requirement: Create and update services derive hostname from template schema and user values
During create-deployment and update-deployment, the service MUST derive `DeploymentORM.hostname` from `user_values_json` using the schema from `desired_template`. The schema field is identified by `title` matching `hostname` (case-insensitive).

Additionally, the create-deployment service MUST generate and persist both `DeploymentORM.name` (Helm release name) and `DeploymentORM.namespace` (Kubernetes namespace) at creation time, using the naming functions defined in the `deployment-naming` and `deployment-namespace` capabilities.

#### Scenario: Template schema contains a hostname-titled field
- **WHEN** the desired template schema contains one or more fields anywhere in the schema document whose `title` matches `hostname` case-insensitively
- **THEN** the service selects the first matching field and persists `DeploymentORM.hostname` from the corresponding `user_values_json` value

#### Scenario: Template schema has no hostname-titled field
- **WHEN** the desired template schema contains no field whose `title` equals `hostname`
- **THEN** the service persists `DeploymentORM.hostname` as `null`

#### Scenario: Update re-derives hostname
- **WHEN** a client updates a deployment with new `user_values_json`
- **THEN** the service re-derives and persists `DeploymentORM.hostname` using the same recursive first-match rule

#### Scenario: Deployment creation generates name and namespace
- **WHEN** a new deployment is created
- **THEN** the service generates `name` using `generate_deployment_name(product_name)` and `namespace` using `generate_deployment_namespace(user_email)`
- **AND** both values are persisted to the deployment record before flushing

### Requirement: Create and update services validate hostname before persisting
During create-deployment and update-deployment, after deriving the hostname, the service MUST call `require_valid_hostname_for_deployment()` to validate the hostname before flushing to the database. If validation fails, the service MUST raise an appropriate exception and not persist the deployment.

#### Scenario: Deployment creation with invalid hostname
- **WHEN** a client creates a deployment whose derived hostname fails validation (e.g., reserved, in use, not resolving)
- **THEN** the API returns an error response and the deployment is not created

#### Scenario: Deployment update with invalid hostname
- **WHEN** a client updates a deployment and the new derived hostname fails validation
- **THEN** the API returns an error response and the deployment is not updated

#### Scenario: Deployment with no hostname field skips validation
- **WHEN** a deployment is created or updated and the derived hostname is `null`
- **THEN** hostname validation is skipped and the deployment proceeds normally

### Requirement: Dashboard deployment form removes dedicated Domain name field
The UI Dashboard MUST not render a dedicated `Domain name` TextField and MUST not include a top-level `hostname` (formerly `domainname`) in deployment write payloads.

#### Scenario: User submits deployment form
- **WHEN** the user completes and submits the deployment create form
- **THEN** the generated request payload excludes `hostname`

### Requirement: Update payload allows same template version
The system MUST accept a `PUT /deployments` request whose `desired_template_id`
equals the deployment's current value (a no-op re-apply) instead of rejecting it
as a downgrade.

#### Scenario: Update payload allows same template version
- **WHEN** a client sends a `PUT /deployments` request with `desired_template_id` equal to the current value
- **THEN** the API accepts the request (previously rejected with "Can only upgrade to newer versions")

### Requirement: Deployment creation response includes checkout URL for paid plans

The `POST /users/{user_id}/deployments` endpoint SHALL return an envelope response
containing both the deployment resource and an optional checkout URL:

```json
{
  "deployment": { "id": "a1b2c3d4-...", "status": "pending", "subscription_id": 42, ... },
  "checkout_url": "https://payments.mollie.com/checkout/..."
}
```

For free plans (`price_cents = 0`) or when no payment provider is configured,
`checkout_url` SHALL be `null` and the `deployment.status` SHALL be `"provisioning"`
(existing behavior).

For paid plans with a payment provider configured, `checkout_url` SHALL contain the
Mollie hosted checkout URL and `deployment.status` SHALL be `"pending"`.

This envelope response applies ONLY to the creation endpoint. All other deployment
endpoints (`GET`, `PUT`, `DELETE`) SHALL continue to return the bare deployment
resource unchanged.

#### Scenario: Paid deployment creation returns checkout URL
- **WHEN** `POST /users/{user_id}/deployments` is called with a paid plan template
- **AND** a payment provider is configured
- **THEN** the response is 201 with body:
  - `deployment`: the deployment resource with `status = "pending"`
  - `checkout_url`: a Mollie checkout URL string

#### Scenario: Free deployment creation returns null checkout URL
- **WHEN** `POST /users/{user_id}/deployments` is called with a free plan template
- **THEN** the response is 201 with body:
  - `deployment`: the deployment resource with `status = "provisioning"`
  - `checkout_url`: `null`

#### Scenario: No payment provider returns null checkout URL
- **GIVEN** `CAELUS_MOLLIE_API_KEY` is not configured
- **WHEN** `POST /users/{user_id}/deployments` is called with any plan template
- **THEN** the response is 201 with `checkout_url: null`
- **AND** the deployment is created as if the plan were free

#### Scenario: GET deployment returns bare resource (no envelope)
- **WHEN** `GET /users/{user_id}/deployments/{id}` is called
- **THEN** the response is the deployment resource directly (no `checkout_url` wrapper)

### Requirement: Frontend redirects to Mollie checkout for paid plans

The frontend SHALL redirect the user's browser to a non-null `checkout_url` from
the deployment creation API response using `window.location.href = checkout_url`.
This abandons the current SPA state.

After payment (or cancellation), Mollie redirects the user back to the configured
`CAELUS_MOLLIE_REDIRECT_URL` (the dashboard). The app reloads and shows the
deployment card in its current state.

#### Scenario: Frontend redirect on paid plan
- **GIVEN** the user clicks "Launch" on a paid plan
- **WHEN** the API response includes `checkout_url = "https://payments.mollie.com/..."`
- **THEN** the browser navigates to the checkout URL
- **AND** the DeployDialog does not close normally (browser leaves the page)

#### Scenario: Frontend closes dialog on free plan
- **GIVEN** the user clicks "Launch" on a free plan
- **WHEN** the API response includes `checkout_url = null`
- **THEN** the DeployDialog closes normally (existing behavior)
- **AND** the deployment card appears on the dashboard

### Requirement: CLI refuses paid plan deployment creation

The `deploy create` CLI command SHALL refuse to create deployments for paid plans
when a payment provider is configured, because the CLI cannot redirect a browser
for Mollie checkout.

Free plan deployments via CLI SHALL continue to work as before.

#### Scenario: CLI create with paid plan
- **GIVEN** a payment provider is configured
- **AND** the plan template has `price_cents > 0`
- **WHEN** `deploy create --plan-template-id <paid_id> --template-id <id>` is run
- **THEN** the CLI exits with an error message indicating that paid deployments
  must be created via the web dashboard

#### Scenario: CLI create with free plan
- **GIVEN** a plan template with `price_cents = 0`
- **WHEN** `deploy create --plan-template-id <free_id> --template-id <id>` is run
- **THEN** the deployment is created successfully (existing behavior)

### Requirement: Deployment create requires prior ToS acceptance

Deployment create MUST NOT carry any ToS field, for either REST
`POST /users/{user_id}/deployments` or the equivalent CLI command. Instead it
MUST require that the owning user has already accepted the current Terms of
Service (recorded via `POST /api/me/tos-acceptance`). A create for a user who has not accepted MUST be
rejected with a client error (**400**) and MUST NOT create a deployment. This
guard is enforced server-side so the two-step accept-then-deploy flow cannot be
bypassed by a direct API or CLI client.

#### Scenario: Deploy after acceptance succeeds

- **WHEN** a user who has recorded ToS acceptance creates a deployment with an
  otherwise valid payload
- **THEN** the API creates the deployment, and its payload and response contain
  no ToS field

#### Scenario: Deploy without acceptance is rejected

- **WHEN** a user who has not accepted the Terms attempts to create a deployment
- **THEN** the API responds **400** and no deployment is created

#### Scenario: CLI deploy without acceptance is rejected

- **WHEN** an operator runs the CLI create-deployment command for a user who has
  not accepted
- **THEN** the command fails without creating a deployment

### Requirement: Deployment create and update accept vars as a write-only field
The deployment create and update payloads SHALL accept a `vars` field carrying the same
wire shape as the vars sub-resource. The field SHALL be write-only: it MUST NOT appear on
any deployment read model.

Accepting vars on create is what allows a deployment's **first** release to run with its
configuration, rather than necessarily running once without it and picking it up on a
later rollout.

The field carries a flat map of keys, with no phase dimension: vars submitted this way
are **runtime** vars. That is not a simplification to be revisited — a value consumed
before the deployment exists cannot be supplied on the request that creates it, because
the image is built first (see `cli-deploy`).

On update, `vars` SHALL be merged into the deployment's existing vars, not replace them:
a rollout that says nothing about vars MUST NOT delete them.

Vars submitted this way SHALL be validated and stored exactly as those submitted to the
vars sub-resource, and SHALL be captured by the release the request creates.

#### Scenario: Creating a deployment with vars
- **WHEN** a caller creates a deployment with two vars
- **THEN** the deployment's head holds both
- **AND** the first release's snapshot holds both

#### Scenario: The field is not echoed
- **WHEN** a caller creates or updates a deployment with vars
- **THEN** the response does not contain the submitted `vars` field

#### Scenario: Updating without mentioning vars
- **WHEN** a caller updates a deployment and omits `vars`
- **THEN** the deployment's existing vars are unchanged and are captured by the new
  release

#### Scenario: Updating with one var
- **WHEN** a caller updates a deployment supplying one var, and head holds two others
- **THEN** all three are in head afterwards

### Requirement: A deployment read reports its vars and whether they are running
A single-deployment read SHALL report the deployment's current vars — its head, which is
desired state, matching `user_values_json` — together with a `pending` flag as defined in
`deployment-vars-api`.

Head is reported rather than the applied release's snapshot because the rest of the read
model reports intent; mixing desired chart values with applied runtime values in one
response is the confusion `pending` exists to expose.

Vars SHALL NOT be included in the deployment **list** response, which would make it a
per-row lookup and would fatten a payload that no caller reads vars from.

#### Scenario: Reading one deployment
- **WHEN** a caller reads a deployment that has vars
- **THEN** the response carries the head, with sensitive values omitted
- **AND** it carries `pending`

#### Scenario: Listing deployments
- **WHEN** a caller lists deployments
- **THEN** no deployment in the list carries vars

### Requirement: The stored hostname column permits no value
The `deployment.hostname` column SHALL permit NULL. A deployment whose desired
template declares no hostname-titled field is a valid deployment, and storing
it MUST NOT be rejected by the database.

This closes a contradiction between the schema and the requirement "Create and
update services derive hostname from template schema and user values", whose
scenario "Template schema has no hostname-titled field" already requires the
service to persist `DeploymentORM.hostname` as `null`.

#### Scenario: Creating a deployment from a template with no hostname field
- **WHEN** a deployment is created from a desired template whose schema
  contains no field titled `hostname`
- **THEN** the deployment SHALL be persisted with `hostname` set to `null`
- **AND** the database SHALL accept the insert

#### Scenario: Updating a deployment onto a template with no hostname field
- **WHEN** a deployment is updated so that its re-derived hostname is `null`
- **THEN** the deployment SHALL be persisted with `hostname` set to `null`
- **AND** the database SHALL accept the update

#### Scenario: A deployment that does have a hostname
- **WHEN** a deployment is created from a template that does declare a
  hostname-titled field
- **THEN** the derived hostname SHALL be persisted as before, and the relaxed
  constraint SHALL change nothing about validation or uniqueness

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
MUST be rejected and MUST NOT create a deployment. An **update** that moves an existing
deployment's hostname under another account's subdomain MUST be rejected the same way: the
hazard is the hostname, not the operation that set it. The check MUST run wherever the owner
is known — at deployment create and update — because the hostname validator is given a name
and a session and has no notion of an owner.

This is the one part of the subdomain contract that an update does apply. The *precondition*
— that the account holds a subdomain at all — remains create-only.

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

#### Scenario: An update cannot move a deployment under another subdomain

- **WHEN** a user holding `bob` updates a deployment's hostname to
  `photos.alice.freepod.eu`
- **THEN** the update is rejected

#### Scenario: A custom domain is unaffected

- **WHEN** a user creates a deployment with hostname `photos.example.com` and `example.com`
  is not a configured wildcard domain
- **THEN** the ownership rule does not apply
