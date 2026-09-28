# app-auth-chart-contract Specification

## Purpose

Defines how a `custom` deployment opts in to app authentication through its values, and what the `custom` chart and the reconciler must render and inject so the edge enforces it.

## Requirements

### Requirement: Authentication is declared in the deployment's values

The `custom` template's values schema SHALL accept an optional `auth` object:

```json
{ "auth": { "enabled": true, "public": ["^/$", "^/static/"] } }
```

- `enabled` is a boolean and defaults to `false`.
- `public` is an optional array of at most 32 strings, each at most 256 characters.
- Unknown keys inside `auth` SHALL be rejected.

Because `auth` travels in `user_values`, a developer SHALL be able to set it in `.freepod.json` with no dedicated command, flag or API.

#### Scenario: Opt in from the project file

- **WHEN** a developer adds `"auth": {"enabled": true}` under `user_values` in `.freepod.json` and runs `freepod deploy`
- **THEN** the deployment serves with authentication enabled

#### Scenario: Unknown key

- **WHEN** a deployment is submitted with `"auth": {"enabled": true, "allow": ["bob@example.com"]}`
- **THEN** it is rejected by schema validation

#### Scenario: Opt out

- **WHEN** a deployment with authentication enabled is updated with `"auth": {"enabled": false}`, or with no `auth`
- **THEN** after the release, requests reach the app without sign-in and without identity headers

### Requirement: Authentication enforced at the edge when enabled

When `auth.enabled` is true, the chart SHALL route every request for the deployment's hostname through the platform verifier before the app. That includes every path, every method, and the custom-domain hostname if the deployment has one. The verifier's address SHALL come only from values the reconciler injects, and SHALL NOT be settable through user values. If the reconciler has not injected the verifier's address, a chart with authentication enabled SHALL fail to render rather than serve the app unauthenticated.

#### Scenario: Every route is covered

- **WHEN** the rendered manifests of an auth-enabled deployment are inspected
- **THEN** every route that forwards to the app passes through the verifier

#### Scenario: Missing platform configuration

- **WHEN** an auth-enabled deployment is rendered without the reconciler-injected verifier address
- **THEN** rendering fails and the previous release keeps serving

#### Scenario: User cannot redirect the verifier

- **WHEN** a deployment's user values attempt to set the verifier address
- **THEN** schema validation rejects them

### Requirement: Identity headers stripped on every custom deployment

Every `custom` deployment with a hostname SHALL remove the headers `X-Freepod-User`, `X-Freepod-Email`, `X-Freepod-Name`, `X-Freepod-Jwt`, `Remote-User`, `X-Forwarded-User` and `X-Forwarded-Email` from incoming requests before they reach the app, whether or not it has enabled authentication. This keeps an app that reads these headers without opting in from being trivially spoofed.

#### Scenario: App without authentication reads the header

- **WHEN** a client sends `X-Freepod-Email: admin@example.com` to a `custom` deployment that has not enabled authentication
- **THEN** the app receives no `X-Freepod-Email` header

### Requirement: Reconciler injects the verifier address

The reconciler SHALL inject the environment's verifier address into every `custom` deployment's chart values, under a platform-owned key. The address SHALL be the same for all of an environment's deployments. No per-deployment state SHALL be needed to enable or disable authentication beyond the deployment's own values.

#### Scenario: Injected value

- **WHEN** the chart values the reconciler renders for a production `custom` deployment are inspected
- **THEN** they contain the production verifier's in-cluster address under the platform-owned key
