## ADDED Requirements

### Requirement: Settings name the environment the platform is running as
The `CaelusSettings` class MUST include an `environment` field naming the environment the platform is deployed as (`prod`, `dev`), supplied per environment alongside the other per-environment values. It MUST default to a value other than production, so that a platform which has not been told what it is never acts as the production one.

The platform runs more than one environment against shared infrastructure, and configuration that varies between them is otherwise expressed only as individual values — a hostname, a port, a namespace — from which the environment itself cannot be recovered. This field is the one place that distinction is named.

#### Scenario: The environment is supplied per environment
- **WHEN** an environment is deployed
- **THEN** `get_settings().environment` returns that environment's name

#### Scenario: An unconfigured platform is not production
- **WHEN** the application starts without `CAELUS_ENVIRONMENT` set
- **THEN** `get_settings().environment` returns a value other than `prod`
