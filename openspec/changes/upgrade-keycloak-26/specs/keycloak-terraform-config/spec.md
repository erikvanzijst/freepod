# Spec Delta

## MODIFIED Requirements

### Requirement: Keycloak configuration is declared in Terraform

The system SHALL manage Keycloak realm, client, client-scope and group
configuration as Terraform code using the `keycloak/keycloak` provider, rather
than through the Keycloak admin console.

#### Scenario: Provider is declared

- **WHEN** the `tf/deps` provider configuration is inspected
- **THEN** a required provider with source `keycloak/keycloak` is declared
- **AND** the version constraint resolves to 5.x or later
- **AND** the unmaintained `mrparkers/keycloak` provider is not used

#### Scenario: Provider supports the running server

- **WHEN** the provider version constraint is compared with the running
  Keycloak's major version
- **THEN** the resolved provider release supports that major version
- **AND** any cap held for an older server is removed in the same change that
  retires that server

#### Scenario: Realm configuration is reproducible from code

- **WHEN** an operator inspects the `freepod` realm's registration policy, email
  verification setting, SMTP server and themes
- **THEN** each value is expressed in Terraform and no manual admin-console step
  is required to reproduce it

#### Scenario: Console changes are reverted by apply

- **WHEN** a managed attribute is changed by hand in the Keycloak admin console
- **AND** `terraform apply` is subsequently run in `tf/deps`
- **THEN** the attribute is restored to the value declared in code
