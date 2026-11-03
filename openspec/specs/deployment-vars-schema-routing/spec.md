# deployment-vars-schema-routing Specification

## Purpose
Defines how a product template's single value schema declares which of its properties
configure the Helm chart and which become a pod's environment, so that one schema drives
one form and the platform still has exactly one channel into a pod's environment.
## Requirements
### Requirement: One schema routes each property to the chart or to the pod environment
A product template's value schema SHALL declare routing per property using
`x-caelus-target`, whose value is `chart` or `runtime`. A property that omits the keyword
SHALL be treated as `chart`, so an existing schema keeps its current meaning with no
edit.

There SHALL NOT be a second schema, nor a reserved container property, for runtime
values. Because routing is a marker on properties of one object, chart and runtime
properties are disjoint subsets of one namespace and a template author cannot declare a
name that means one thing in one channel and another in the other.

#### Scenario: An existing schema with no markers
- **WHEN** a template's schema declares properties and none carries `x-caelus-target`
- **THEN** every property routes to the chart
- **AND** the template accepts no vars

#### Scenario: A schema with a runtime property
- **WHEN** a schema declares `host` unmarked and `ADMIN_TOKEN` with
  `x-caelus-target: runtime`
- **THEN** `host` is submitted as a chart value
- **AND** `ADMIN_TOKEN` is submitted as a var

### Requirement: Runtime routing is legal only on top-level scalar properties
`x-caelus-target: runtime` SHALL be accepted only on a property of the schema's root
object whose type is `string`, `number`, `integer` or `boolean`. It MUST be rejected on
a nested property, on an object, and on an array.

A runtime property's name SHALL match `^[A-Za-z_][A-Za-z0-9_]{0,63}$` and MUST NOT be a
reserved name (see `deployment-vars-api`). The property name is the environment variable
name; no flattening or renaming is applied anywhere.

`x-caelus-sensitive: true` SHALL be accepted only on a property that is also
`x-caelus-target: runtime`.

A schema violating any of these rules SHALL be rejected when the template is created and
when the catalog is loaded, so the failure lands on the author rather than on a tenant's
next deployment.

#### Scenario: Runtime marker on a nested property
- **WHEN** a schema marks `signups.allowed` as `x-caelus-target: runtime`
- **THEN** the schema is rejected with an error naming the property

#### Scenario: Runtime marker on an object property
- **WHEN** a schema marks an object-typed top-level property as `runtime`
- **THEN** the schema is rejected

#### Scenario: A runtime property named like a chart path
- **WHEN** a schema marks a runtime property named `signups.allowed`
- **THEN** the schema is rejected because the name is not a legal environment variable
  name

#### Scenario: Sensitivity on a chart property
- **WHEN** a schema marks a property `x-caelus-sensitive: true` without
  `x-caelus-target: runtime`
- **THEN** the schema is rejected

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

### Requirement: A product accepts no vars unless its schema declares them
Closed by default SHALL require no per-product declaration. A template whose schema
declares no runtime property SHALL derive a vars projection that is an empty object
forbidding unknown properties, and SHALL therefore reject every var. A template with no
value schema at all SHALL reject vars outright, mirroring the existing treatment of
user values.

#### Scenario: A curated product with no runtime properties
- **WHEN** a caller submits any var to a deployment of a product whose schema marks
  nothing as runtime
- **THEN** the request is rejected

#### Scenario: A template with no value schema
- **WHEN** a caller submits any var to a deployment whose template declares no value
  schema
- **THEN** the request is rejected

### Requirement: A schema may open its vars projection to undeclared keys
A schema MAY set `x-caelus-vars-additional: true` at its root, which SHALL make the
derived vars projection accept properties it does not declare. This SHALL NOT affect the
chart projection, which keeps the root's own `additionalProperties`.

This exists for a product that runs tenant-supplied code and therefore cannot enumerate
its environment in advance, while its chart values stay closed.

#### Scenario: An open vars projection
- **WHEN** a template's schema sets `x-caelus-vars-additional: true` and
  `additionalProperties: false`
- **THEN** a var with an undeclared key is accepted
- **AND** a chart value with an undeclared key is still rejected

### Requirement: Sensitivity is declared by the schema where the schema declares the property
Where the vars projection declares a property, `x-caelus-sensitive` SHALL determine
whether the var is sensitive. A caller MAY omit sensitivity, in which case the schema's
value SHALL be used; a caller that states a value contradicting the schema SHALL be
rejected rather than silently overridden.

Where the vars projection does not declare the property — an open projection — the
caller SHALL determine sensitivity, defaulting to not sensitive.

Rejecting a contradiction rather than overriding it turns a client defect into an error
instead of quietly downgrading a secret to a readable value.

#### Scenario: Sensitivity omitted by the caller
- **WHEN** a caller sets a var the schema declares `x-caelus-sensitive: true`, without
  stating sensitivity
- **THEN** the var is stored as sensitive

#### Scenario: Sensitivity contradicting the schema
- **WHEN** a caller sets that same var stating `sensitive: false`
- **THEN** the request is rejected

#### Scenario: An undeclared key on an open projection
- **WHEN** a caller sets an undeclared var without stating sensitivity
- **THEN** the var is stored as not sensitive

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
