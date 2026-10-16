# Spec Delta

## MODIFIED Requirements

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

### Requirement: Reconciler injects the verifier address

The reconciler SHALL inject the environment's verifier address into every deployment's chart values, whatever its product, under a platform-owned key. The address SHALL be the same for all of an environment's deployments. No per-deployment state SHALL be needed to enable or disable authentication beyond the deployment's own values and its template's system values.

#### Scenario: Injected value

- **WHEN** the chart values the reconciler renders for a production deployment are inspected
- **THEN** they contain the production verifier's in-cluster address under the platform-owned key

## ADDED Requirements

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
