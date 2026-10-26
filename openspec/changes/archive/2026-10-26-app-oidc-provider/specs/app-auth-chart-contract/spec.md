# Spec Delta

## MODIFIED Requirements

### Requirement: A template may turn authentication on

A product's template MAY set `auth.enabled` as a system value. When it does, the value SHALL be the default for every deployment of that template, a user value SHALL override it as it overrides any chart value, and the merged value SHALL be what the broker and the edge both act on. A template that must not be overridden SHALL leave `auth.enabled` out of its user values schema.

#### Scenario: Always-on authentication

- **WHEN** a template sets `auth.enabled: true` as a system value and a deployment's user values do not mention `auth`
- **THEN** the deployment serves with authentication enabled

#### Scenario: Forced on by the template

- **WHEN** a template sets `auth.enabled: true` as a system value and its user values schema has no `auth` property
- **THEN** every deployment of the template serves with authentication enabled, and no tenant can turn it off
