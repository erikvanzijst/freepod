# Spec Delta

## ADDED Requirements

### Requirement: Only deployments with authentication enabled are served

Before sending a browser to the identity provider, and again before issuing a code, the broker SHALL confirm that the requested host is the hostname of a deployment that is not deleted and has authentication enabled, whatever its product. The comparison SHALL be case-insensitive. Whether authentication is enabled SHALL be judged from the release the deployment is currently serving, not from settings not yet rolled out, so the broker agrees with what the edge enforces: the release's user value for `auth.enabled` when it sets one, otherwise the template's system value, otherwise disabled. This SHALL apply to wildcard-domain and custom-domain hostnames alike. For any other host, the broker SHALL show an error page and SHALL NOT redirect anywhere.

#### Scenario: Custom domain

- **WHEN** sign-in starts for `shop.example.com`, the hostname of an auth-enabled `custom` deployment
- **THEN** the broker proceeds

#### Scenario: Host without authentication enabled

- **WHEN** sign-in is requested for the hostname of a deployment that has not enabled authentication
- **THEN** the broker shows an error and issues no code

#### Scenario: Arbitrary host

- **WHEN** sign-in is requested for `evil.example`
- **THEN** the broker shows an error and does not redirect

#### Scenario: Authentication disabled mid-flow

- **WHEN** a deployment disables authentication after a user was sent to the identity provider, and the user then returns to the broker
- **THEN** the broker issues no code

#### Scenario: Another product

- **WHEN** sign-in starts for the hostname of an auth-enabled deployment of a product other than `custom`
- **THEN** the broker proceeds

#### Scenario: Enabled by the template

- **WHEN** sign-in starts for a deployment whose template sets `auth.enabled: true` as a system value and whose user values say nothing about `auth`
- **THEN** the broker proceeds

#### Scenario: User value over the template's default

- **WHEN** a deployment's template sets `auth.enabled: true` as a system value and its user values set `auth.enabled: false`
- **THEN** the broker treats authentication as disabled, as the chart renders it

## REMOVED Requirements

### Requirement: Only auth-enabled deployments are served

**Reason**: It read `auth.enabled` with the template's system value over the user value, on the mistaken belief that the reconciler merges template system values last. It merges them first, as chart defaults, so the requirement could make the broker disagree with what the chart renders. Replaced by "Only deployments with authentication enabled are served", which reads the user value first.
**Migration**: None. No product's user values schema exposes `auth.enabled` alongside a template system value, so every deployment is judged the same before and after.
