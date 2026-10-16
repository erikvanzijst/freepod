# Spec Delta

## MODIFIED Requirements

### Requirement: Only auth-enabled deployments are served

Before sending a browser to the identity provider, and again before issuing a code, the broker SHALL confirm that the requested host is the hostname of a deployment that is not deleted and has authentication enabled, whatever its product. The comparison SHALL be case-insensitive. Whether authentication is enabled SHALL be judged from the release the deployment is currently serving, not from settings not yet rolled out, so the broker agrees with what the edge enforces: the release's template system value for `auth.enabled` when the template sets one, otherwise the release's user value, otherwise disabled. This SHALL apply to wildcard-domain and custom-domain hostnames alike. For any other host, the broker SHALL show an error page and SHALL NOT redirect anywhere.

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

#### Scenario: Template value wins

- **WHEN** a deployment's template sets `auth.enabled: true` as a system value and its user values set `auth.enabled: false`
- **THEN** the broker treats authentication as enabled, as the edge does

## ADDED Requirements

### Requirement: Preview hostnames sign in as their deployment
When the requested host is not itself a deployment's hostname but has the form `preview-<label>.<rest>`, the broker SHALL treat it as the deployment at `<label>.<rest>`, provided that deployment qualifies under *Only auth-enabled deployments are served*. The broker SHALL derive this from the hostname and its own records only, never from anything in the request naming an alias.

#### Scenario: Preview of an auth-enabled deployment
- **WHEN** sign-in starts for `preview-studio.alice.freepod.eu` and `studio.alice.freepod.eu` is an auth-enabled deployment
- **THEN** the broker proceeds as for `studio.alice.freepod.eu`, and issues a code bound to `preview-studio.alice.freepod.eu`

#### Scenario: Base deployment without authentication
- **WHEN** sign-in starts for `preview-shop.alice.freepod.eu` and `shop.alice.freepod.eu` has not enabled authentication
- **THEN** the broker shows an error and issues no code

#### Scenario: Unknown base host
- **WHEN** sign-in starts for `preview-nothing.alice.freepod.eu` and no deployment has `nothing.alice.freepod.eu`
- **THEN** the broker shows an error and does not redirect

### Requirement: One consent covers a deployment's hostnames
Consent SHALL remain recorded per deployment. A user who has consented on a deployment's hostname SHALL NOT be asked again on its preview hostname, and the reverse.

#### Scenario: Consent carried to the preview
- **WHEN** Alice has consented on `studio.alice.freepod.eu` and then signs in on `preview-studio.alice.freepod.eu`
- **THEN** she is not asked for consent again
