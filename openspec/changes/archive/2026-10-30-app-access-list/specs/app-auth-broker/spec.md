# Spec Delta

## ADDED Requirements

### Requirement: Signing in ties a listed entry to the account

When a person signs in to a `listed` deployment through an unbound entry that matches their verified email, the broker SHALL record their subject and display name on that entry before it issues a code, for either protocol. It SHALL NOT change an entry that is already tied to a subject.

#### Scenario: First sign-in

- **WHEN** `jules@example.org` is listed, unbound, and Jules signs in to the deployment for the first time
- **THEN** the entry holds Jules's subject and name before the code is issued

#### Scenario: Concurrent first sign-ins

- **WHEN** Jules completes sign-in in two browsers at the same moment against the same unbound entry
- **THEN** both sign-ins succeed and the entry is tied to Jules's subject once

#### Scenario: Entry already tied

- **WHEN** an entry is tied to one subject and a different subject signs in with the entry's email
- **THEN** the entry is unchanged and the broker refuses the sign-in

## MODIFIED Requirements

### Requirement: Only deployments with authentication enabled are served

Before sending a browser to the identity provider, and again before issuing a code, the broker SHALL confirm that the requested host is the hostname of a deployment that is not deleted and has header authentication enabled, whatever its product. The comparison SHALL be case-insensitive. Whether header authentication is enabled SHALL be judged from the release the deployment is currently serving, not from settings not yet rolled out, so the broker agrees with what the edge enforces: `auth.enabled` and `auth.protocol` each from the release's user value when it sets one, otherwise the template's system value, otherwise the contract's default, and enabled only when `auth.enabled` is true and `auth.protocol` is `header`. This SHALL apply to wildcard-domain and custom-domain hostnames alike. For any other host, the broker SHALL show an error page and SHALL NOT redirect anywhere.

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

#### Scenario: OIDC deployment

- **WHEN** header sign-in is requested for the hostname of a deployment with `auth.enabled: true` and `auth.protocol: oidc`
- **THEN** the broker shows an error and issues no code

### Requirement: Any Freepod account may sign in

Any Freepod account with a verified email SHALL be able to sign in to any auth-enabled app whose serving release has `auth.access: anyone`, and authorization inside such an app is the app's responsibility. For an app with `auth.access: listed`, the broker SHALL admit only the deployment's owner and the people on its access list, and SHALL refuse anyone else after they authenticate and before any consent page, with the no-access page on the broker's host and no code.

#### Scenario: Stranger signs in

- **WHEN** a Freepod user with no relation to an app's owner signs in to an app with `auth.access: anyone`
- **THEN** sign-in succeeds and the app receives their identity

#### Scenario: Stranger on a listed app

- **WHEN** a Freepod user who is neither the owner nor listed signs in to an app with `auth.access: listed`
- **THEN** the broker shows the no-access page, shows no consent page, and issues no code

#### Scenario: Owner on a listed app

- **WHEN** the owner signs in to their app with `auth.access: listed` and an empty list
- **THEN** sign-in succeeds
