# keycloak-terraform-config Specification

## Purpose
Keep Keycloak realm, client, client-scope and group configuration in Terraform
rather than the admin console, so the identity provider's configuration is
reviewable, reproducible and diffable. Defines where that configuration lives
(the singleton `tf/deps` root module), how the workspaced `tf/app` module
selects per-environment credentials from it, and the destroy guards that keep
Terraform from reaching user data — end-user accounts and group membership are
deliberately left outside Terraform's control.

## Requirements
### Requirement: Keycloak configuration is declared in Terraform

The system SHALL manage Keycloak realm, client, client-scope and group
configuration as Terraform code using the `keycloak/keycloak` provider, rather
than through the Keycloak admin console.

#### Scenario: Provider is declared

- **WHEN** the `tf/deps` provider configuration is inspected
- **THEN** a required provider with source `keycloak/keycloak` is declared
- **AND** the version constraint resolves to 5.x or later
- **AND** the unmaintained `mrparkers/keycloak` provider is not used

#### Scenario: Realm configuration is reproducible from code

- **WHEN** an operator inspects the `freepod` realm's registration policy, email
  verification setting, SMTP server and themes
- **THEN** each value is expressed in Terraform and no manual admin-console step
  is required to reproduce it

#### Scenario: Console changes are reverted by apply

- **WHEN** a managed attribute is changed by hand in the Keycloak admin console
- **AND** `terraform apply` is subsequently run in `tf/deps`
- **THEN** the attribute is restored to the value declared in code

### Requirement: The realm resource is protected from destruction

The `freepod` realm SHALL be managed as a Terraform resource carrying a
`prevent_destroy` lifecycle guard, because destroying a Keycloak realm cascades
to every user, credential and session it contains.

#### Scenario: Destroy is refused

- **WHEN** a Terraform plan would destroy or replace the `keycloak_realm`
  resource for `freepod`
- **THEN** Terraform fails with a hard error
- **AND** no realm deletion is performed

#### Scenario: Realm attributes remain updatable

- **WHEN** a non-force-new realm attribute such as the SMTP host is changed in
  code and applied
- **THEN** the change is applied in place without replacing the realm

### Requirement: Terraform does not manage end-user accounts

The system SHALL NOT declare end-user accounts as Terraform resources. User
records SHALL remain owned by Keycloak's own datastore so that no Terraform
operation can enumerate, modify or delete them.

#### Scenario: No user resources are declared

- **WHEN** the Keycloak Terraform configuration is inspected
- **THEN** no `keycloak_user` resource represents an end-user account

#### Scenario: Self-registration is unaffected by apply

- **WHEN** a user self-registers through the Keycloak registration form
- **AND** `terraform apply` is subsequently run
- **THEN** the account is left untouched and does not appear as configuration
  drift

### Requirement: Realm configuration lives in the singleton root module

Keycloak configuration SHALL be declared in the `tf/deps` root module, which
manages shared singleton dependencies and uses no Terraform workspaces. Both
per-environment clients SHALL be declared there as distinct resources rather
than as a single resource parameterized by workspace.

#### Scenario: Both clients are declared in tf/deps

- **WHEN** the `tf/deps` Keycloak configuration is inspected
- **THEN** `freepod-prod` and `freepod-dev` are each declared as their own
  client resource
- **AND** neither is conditioned on `terraform.workspace`

#### Scenario: tf/app selects rather than declares

- **WHEN** the `tf/app` root module is inspected
- **THEN** it selects which client ID and secret to use for the current
  workspace
- **AND** it declares no Keycloak realm, client, client-scope or group resource

### Requirement: Per-workspace client credentials are keyed by workspace name

The oauth2-proxy client ID and secret variables SHALL be maps keyed by Terraform
workspace name rather than scalars, and SHALL be indexed by
`terraform.workspace`. A scalar cannot express two per-environment values,
because Terraform loads `*.auto.tfvars` for every workspace.

#### Scenario: Each workspace resolves its own client

- **WHEN** `tf/app` is applied in the `prod` workspace
- **THEN** the `freepod-prod` client ID and its secret are used
- **WHEN** `tf/app` is applied in the `default` workspace
- **THEN** the `freepod-dev` client ID and its secret are used

#### Scenario: Map keys match actual workspace names

- **WHEN** the client credential map keys are inspected
- **THEN** they are `default` and `prod`, matching the workspaces that exist
- **AND** no key named `dev` is used, since no workspace by that name exists

#### Scenario: Secrets remain in manually maintained tfvars

- **WHEN** the client secret plumbing is inspected
- **THEN** values are supplied through the existing gitignored
  `secrets.auto.tfvars` files
- **AND** no `terraform_remote_state` coupling between `tf/app` and `tf/deps` is
  introduced

### Requirement: App-authentication clients per environment

The `freepod` realm SHALL declare one OpenID Connect client per environment for the app authentication broker: `freepod-apps-prod` and `freepod-apps-dev`. Each client SHALL:
- be confidential;
- enable only the standard (authorization code) flow, with PKCE method `S256`;
- disable the implicit flow, direct access grants and service accounts;
- list exactly one valid redirect URI: its environment's broker callback on `login.freepod.eu` or `login.dev.freepod.eu`.

Neither client SHALL use a wildcard redirect URI. Neither SHALL require identity-provider consent, because the broker asks for consent per app itself. The number of clients SHALL NOT grow with the number of deployments.

The broker's client ID and secret SHALL reach `tf/app` the same way the existing client credentials do: as maps keyed by workspace name, supplied through the gitignored `secrets.auto.tfvars`.

#### Scenario: Clients exist per environment

- **WHEN** the realm's clients are inspected
- **THEN** `freepod-apps-prod` and `freepod-apps-dev` exist alongside the existing clients

#### Scenario: Single fixed redirect URI

- **WHEN** the redirect URIs of `freepod-apps-prod` are inspected
- **THEN** there is exactly one, on `https://login.freepod.eu`, and it contains no wildcard

#### Scenario: New deployments need no identity-provider change

- **WHEN** a thousand `custom` deployments enable authentication
- **THEN** the realm still has exactly two app-authentication clients

#### Scenario: Workspace selects its client

- **WHEN** `tf/app` is applied in the `prod` workspace
- **THEN** the broker is configured with the `freepod-apps-prod` client ID and secret
