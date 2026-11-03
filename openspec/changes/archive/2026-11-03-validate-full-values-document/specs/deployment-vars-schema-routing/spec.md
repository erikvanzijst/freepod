## MODIFIED Requirements

### Requirement: Two validation projections are derived from the one schema
The platform SHALL derive, from a template's value schema, a **chart projection** and a
**vars projection** by partitioning the root object's `properties` and `required` on
`x-caelus-target`. Both projections SHALL be complete, valid schemas of the same JSON
Schema dialect as their source.

The chart projection SHALL retain the root's own keywords, including
`additionalProperties`, except the keywords that relate properties to one another:
`allOf`, `anyOf`, `oneOf`, `not`, `if`, `then`, `else`, `dependentRequired`,
`dependentSchemas` and `dependencies`. Those are evaluated against the full submission
only (see "The full submission is validated against the whole schema"). The vars
projection's `additionalProperties` SHALL be the root-level `x-caelus-vars-additional`,
defaulting to `false`.

Chart values SHALL be validated against the chart projection and vars against the vars
projection.

#### Scenario: Deriving both halves
- **WHEN** a schema declares a required `host` (chart) and `SIGNUPS_ALLOWED` and
  `ADMIN_TOKEN` (runtime), with `additionalProperties: false` at the root
- **THEN** the chart projection declares `host`, requires it, and forbids unknown
  properties
- **AND** the vars projection declares `SIGNUPS_ALLOWED` and `ADMIN_TOKEN`, requires
  neither, and forbids unknown properties

#### Scenario: A chart value submitted as a var
- **WHEN** a caller submits `host` as a var against a schema that routes it to the chart
- **THEN** the request is rejected, because `host` is not in the vars projection

#### Scenario: A root conditional is not part of the chart projection
- **WHEN** a schema's root declares `if`/`then`
- **THEN** the chart projection carries neither keyword

## ADDED Requirements

### Requirement: The full submission is validated against the whole schema
On every write that changes a deployment's chart values or vars, the platform SHALL
also validate one document, the chart values merged with the resulting vars (coerced to
their declared types), against the template's whole schema. This is in addition to the
projection checks, and it is what makes a root conditional or combinator spanning both
halves effective.

#### Scenario: A conditional satisfied by a var
- **WHEN** a schema's root requires the runtime property `ADMIN_PASSWORD` when the
  chart value `auth.enabled` is `false`
- **AND** a deployment is created with `auth.enabled: false` and `ADMIN_PASSWORD`
  supplied as a var
- **THEN** the deployment is created

#### Scenario: A conditional left unsatisfied
- **WHEN** that deployment is created with `auth.enabled: false` and no
  `ADMIN_PASSWORD`
- **THEN** the request is rejected naming `vars.ADMIN_PASSWORD` and the `required`
  constraint
- **AND** nothing is stored

#### Scenario: A conditional that does not apply
- **WHEN** that deployment is created with `auth.enabled: true` and no `ADMIN_PASSWORD`
- **THEN** the deployment is created

### Requirement: Every write checks the deployment's resulting combined state
Deployment create, deployment update (including a move to another template) and every
vars API write SHALL run the full-document check against the state the write would
leave. A write that changes one half SHALL be checked together with the stored other
half: an update with the deployment's resulting vars, and a vars write with the
deployment's stored chart values, against the deployment's template.

#### Scenario: An update changes chart values only
- **WHEN** an update sets `auth.enabled: false` on a deployment holding no
  `ADMIN_PASSWORD`
- **THEN** the update is rejected and no release is created

#### Scenario: A stored sensitive var satisfies the rule
- **WHEN** a deployment holds `ADMIN_PASSWORD` and an update omits it
- **THEN** the stored value counts toward the check and the update is accepted

#### Scenario: A move to a template with a new rule
- **WHEN** an administrator moves a deployment to a template whose schema adds a rule
  its stored values and vars do not satisfy
- **THEN** the move is rejected and the deployment stays on its template

#### Scenario: A var write against stored chart values
- **WHEN** a deployment's stored chart values set `auth.enabled: false`
- **AND** a caller deletes `ADMIN_PASSWORD`, or replaces the vars without it
- **THEN** the request is rejected

### Requirement: Which keys each half may hold is decided by the projections
The full-document check SHALL ignore the root's `additionalProperties`,
`unevaluatedProperties`, `patternProperties`, `propertyNames`, `minProperties` and
`maxProperties`. Those govern the keys of the half whose projection carries them, so a
schema whose vars projection is open keeps accepting undeclared vars.

#### Scenario: An open vars projection
- **WHEN** a template's schema sets `x-caelus-vars-additional: true` and
  `additionalProperties: false`
- **THEN** a deployment with undeclared vars passes the full-document check
- **AND** an undeclared chart value is still rejected by the chart projection

#### Scenario: A rule demanding an undeclared var
- **WHEN** that schema's root requires an undeclared `SESSION_SECRET` when
  `auth.enabled` is `true`
- **THEN** a deployment with `auth.enabled: true` is rejected without it and accepted
  with it

### Requirement: A full-document failure keeps the endpoint's status
A full-document failure SHALL be reported as the failed constraint at a location named
`vars.<KEY>` or `user_values_json.<path>`, naming a missing key where one is missing.
It SHALL answer 409 on the deployment create and update endpoints, as their chart-value
failures do, and 400 on the vars API, as its other validation failures do.

#### Scenario: Refused on a deployment endpoint
- **WHEN** a deployment create or update fails the full-document check
- **THEN** the response is 409

#### Scenario: Refused on the vars API
- **WHEN** a vars write fails the full-document check
- **THEN** the response is 400
