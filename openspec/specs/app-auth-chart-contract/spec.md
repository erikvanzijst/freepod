# app-auth-chart-contract Specification

## Purpose

Defines how a deployment opts in to app authentication, through its own values or its template's system values, and what a chart that offers it and the reconciler must render and inject so the edge enforces it.

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

When `auth.enabled` is true, the chart SHALL route every request for the deployment's hostname through the platform verifier before the app. That includes every path, every method, and the custom-domain hostname if the deployment has one, and it applies to any chart that offers authentication, not only `custom`. The verifier's address SHALL come only from values the reconciler injects, and SHALL NOT be settable through user values. If the reconciler has not injected the verifier's address, a chart with authentication enabled SHALL fail to render rather than serve the app unauthenticated.

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

The reconciler SHALL inject the environment's verifier address into every deployment's chart values, whatever its product, under a platform-owned key. The address SHALL be the same for all of an environment's deployments. No per-deployment state SHALL be needed to enable or disable authentication beyond the deployment's own values and its template's system values.

#### Scenario: Injected value

- **WHEN** the chart values the reconciler renders for a production deployment are inspected
- **THEN** they contain the production verifier's in-cluster address under the platform-owned key

### Requirement: A template may turn authentication on

A product's template MAY set `auth.enabled` as a system value. When it does, the value SHALL apply to every deployment of that template, SHALL override the user value, and SHALL be what the broker and the edge both act on.

#### Scenario: Always-on authentication

- **WHEN** a template sets `auth.enabled: true` as a system value and a deployment's user values do not mention `auth`
- **THEN** the deployment serves with authentication enabled

### Requirement: Allowed accounts come only from platform values

A chart that restricts access to particular accounts SHALL build the verifier's allowed-accounts list only from values the reconciler injects (such as the owner's email) or from template system values, never from user values.

#### Scenario: Owner-only chart

- **WHEN** the manifests of a chart that admits only the deployment's owner are rendered
- **THEN** the verifier's allowed-accounts list holds exactly the reconciler-injected owner email
