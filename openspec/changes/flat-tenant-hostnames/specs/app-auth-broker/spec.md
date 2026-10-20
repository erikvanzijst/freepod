# Spec Delta

## MODIFIED Requirements

### Requirement: Preview hostnames sign in as their deployment

When the requested host is not itself a deployment's hostname but its first label begins with `preview-`, as in `preview-<rest>`, the broker SHALL treat it as the deployment at `<rest>` (the host with that prefix removed), provided that deployment qualifies under *Only auth-enabled deployments are served*. The broker SHALL derive this from the hostname and its own records only, never from anything in the request naming an alias.

#### Scenario: Preview of an auth-enabled deployment

- **WHEN** sign-in starts for `preview-studio-alice.freepod.app` and `studio-alice.freepod.app` is an auth-enabled deployment
- **THEN** the broker proceeds as for `studio-alice.freepod.app`, and issues a code bound to `preview-studio-alice.freepod.app`

#### Scenario: Base deployment without authentication

- **WHEN** sign-in starts for `preview-shop-alice.freepod.app` and `shop-alice.freepod.app` has not enabled authentication
- **THEN** the broker shows an error and issues no code

#### Scenario: Unknown base host

- **WHEN** sign-in starts for `preview-nothing-alice.freepod.app` and no deployment has `nothing-alice.freepod.app`
- **THEN** the broker shows an error and does not redirect

### Requirement: One consent covers a deployment's hostnames

Consent SHALL remain recorded per deployment. A user who has consented on a deployment's hostname SHALL NOT be asked again on its preview hostname, and the reverse.

#### Scenario: Consent carried to the preview

- **WHEN** Alice has consented on `studio-alice.freepod.app` and then signs in on `preview-studio-alice.freepod.app`
- **THEN** she is not asked for consent again
