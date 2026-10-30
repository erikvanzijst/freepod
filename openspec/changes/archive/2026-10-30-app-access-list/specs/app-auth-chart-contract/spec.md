# Spec Delta

## ADDED Requirements

### Requirement: One authentication contract for every chart

Every chart that offers Sign in with Freepod SHALL read it from these values, with these defaults: `auth.enabled` (`false`), `auth.protocol`, `header` or `oidc` (`header`), `auth.access`, `anyone` or `listed` (`anyone`), and `auth.public` (empty). The platform SHALL apply the same defaults wherever it reads these values, so the chart, the broker, the verifier and the API agree.

#### Scenario: Only enabled

- **WHEN** a deployment's merged values set `auth.enabled: true` and nothing else under `auth`
- **THEN** the chart renders header authentication open to any Freepod account, and the broker and the API treat it the same way

#### Scenario: Unknown protocol

- **WHEN** a template's system values set `auth.protocol: saml`
- **THEN** the broker and the provider treat the deployment as having no Sign in with Freepod

### Requirement: OIDC settings come only from system values

Values under `auth.oidc` SHALL be read only from template system values. No template's user values schema SHALL declare `auth.oidc`, and the platform SHALL ignore `auth.oidc` in a deployment's user values.

#### Scenario: User-supplied callback

- **WHEN** a deployment's user values carry `auth.oidc.redirectPaths: ["/steal"]`
- **THEN** no part of the platform reads them

### Requirement: Public paths apply only to header authentication

`auth.public` SHALL apply only when `auth.protocol` is `header`, because only header authentication puts the platform in front of the app's requests. A chart with `auth.protocol: oidc` SHALL ignore it.

#### Scenario: Public paths on an OIDC app

- **WHEN** a deployment with `auth.protocol: oidc` sets `auth.public: ["^/share/"]`
- **THEN** its routes carry no forward-auth middleware, and the app decides what is public

### Requirement: Listed header apps ask the verifier to check the list

When `auth.enabled` is true, `auth.protocol` is `header` and `auth.access` is `listed`, the chart SHALL tell the verifier, in its edge configuration, that the deployment's access list applies. The chart SHALL NOT carry the list itself, nor any account, in its values or its rendered manifests.

#### Scenario: Listed custom app

- **WHEN** a custom deployment with `"auth": {"enabled": true, "access": "listed"}` is rendered
- **THEN** its verifier middleware says that the access list applies, and names no account

### Requirement: Templates that enable authentication state their access

A catalog template that sets `auth.enabled: true` as a system value SHALL also set `auth.access` as a system value, so that no product admits every Freepod account by omission. The catalog's validation SHALL fail for a template that does not.

#### Scenario: Access left out

- **WHEN** a catalog template sets `auth.enabled: true` and no `auth.access`
- **THEN** catalog validation fails, naming the template

## MODIFIED Requirements

### Requirement: Authentication is declared in the deployment's values

The `custom` template's values schema SHALL accept an optional `auth` object:

```json
{ "auth": { "enabled": true, "access": "listed", "public": ["^/$", "^/static/"] } }
```

- `enabled` is a boolean and defaults to `false`.
- `access` is `anyone` or `listed` and defaults to `anyone`.
- `public` is an optional array of at most 32 strings, each at most 256 characters.
- Unknown keys inside `auth` SHALL be rejected, including `protocol` and `oidc`: custom deployments authenticate with headers.

Because `auth` travels in `user_values`, a developer SHALL be able to set it in `.freepod.json` with no dedicated command, flag or API.

#### Scenario: Opt in from the project file

- **WHEN** a developer adds `"auth": {"enabled": true}` under `user_values` in `.freepod.json` and runs `freepod deploy`
- **THEN** the deployment serves with authentication enabled, open to any Freepod account

#### Scenario: Only listed people

- **WHEN** a developer sets `"auth": {"enabled": true, "access": "listed"}` and deploys
- **THEN** only the owner and the people on the deployment's access list can sign in

#### Scenario: Unknown key

- **WHEN** a deployment is submitted with `"auth": {"enabled": true, "allow": ["bob@example.com"]}`
- **THEN** it is rejected by schema validation

#### Scenario: Custom app asks for OIDC

- **WHEN** a custom deployment is submitted with `"auth": {"enabled": true, "protocol": "oidc"}`
- **THEN** it is rejected by schema validation

#### Scenario: Opt out

- **WHEN** a deployment with authentication enabled is updated with `"auth": {"enabled": false}`, or with no `auth`
- **THEN** after the release, requests reach the app without sign-in and without identity headers

### Requirement: Authentication enforced at the edge when enabled

When `auth.enabled` is true and `auth.protocol` is `header`, the chart SHALL route every request for the deployment's hostname through the platform verifier before the app. That includes every path, every method, and the custom-domain hostname if the deployment has one, and it applies to any chart that offers authentication, not only `custom`. The verifier's address SHALL come only from values the reconciler injects, and SHALL NOT be settable through user values. If the reconciler has not injected the verifier's address, a chart with header authentication enabled SHALL fail to render rather than serve the app unauthenticated. With `auth.protocol: oidc`, the chart SHALL NOT route requests through the verifier.

#### Scenario: Every route is covered

- **WHEN** the rendered manifests of a deployment with header authentication enabled are inspected
- **THEN** every route that forwards to the app passes through the verifier

#### Scenario: Missing platform configuration

- **WHEN** a deployment with header authentication enabled is rendered without the reconciler-injected verifier address
- **THEN** rendering fails and the previous release keeps serving

#### Scenario: User cannot redirect the verifier

- **WHEN** a deployment's user values attempt to set the verifier address
- **THEN** schema validation rejects them

#### Scenario: OIDC app

- **WHEN** a deployment with `auth.enabled: true` and `auth.protocol: oidc` is rendered
- **THEN** its routes carry no forward-auth middleware

### Requirement: A template may turn authentication on

A product's template MAY set `auth.enabled`, `auth.protocol`, `auth.access` and `auth.public` as system values. Each SHALL be the default for every deployment of that template, a user value SHALL override it as it overrides any chart value, and the merged value SHALL be what the broker, the verifier, the API and the edge all act on. A template whose values must not be overridden SHALL leave them out of its user values schema.

#### Scenario: Always-on authentication

- **WHEN** a template sets `auth.enabled: true` as a system value and a deployment's user values do not mention `auth`
- **THEN** the deployment serves with authentication enabled

#### Scenario: Forced on by the template

- **WHEN** a template sets `auth.enabled: true` and `auth.access: listed` as system values and its user values schema has no `auth` property
- **THEN** every deployment of the template serves with authentication enabled for its owner and its list, and no tenant can change either

## REMOVED Requirements

### Requirement: Allowed accounts come only from platform values

**Reason**: Charts no longer carry a list of allowed accounts. Who may sign in to a `listed` deployment is kept in the platform's access list and edited through the API, so changing it never redeploys the app.

**Migration**: A chart that admitted only the owner sets `auth.access: listed` as a template system value and stops rendering an allowed-accounts list. With an empty access list, only the owner is admitted.
