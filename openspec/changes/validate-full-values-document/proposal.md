## Why

A template's value schema describes chart values and vars as one object, but the
platform only ever validates each half against its own projection, and copies the
root's conditionals and combinators into the chart projection alone. A rule that relates
a chart value to a var therefore cannot be expressed: a schema requiring an admin
password var whenever `auth.enabled` is `false` refuses every such deployment, even
when the var is supplied, because the rule is evaluated against chart values only.

## What Changes

- The platform also validates the full submission — chart values and vars merged into
  one document, vars coerced to their declared types — against the template's whole
  schema, on every write that changes a deployment's values or vars: deployment create,
  deployment update (including a move to another template), and the vars API, which
  checks the resulting vars together with the deployment's stored chart values.
- The per-projection checks stay. They keep deciding which keys each half may hold, so
  the full-document pass ignores the root's key-set keywords (`additionalProperties`
  and kin) and a `custom`-style open vars half keeps accepting undeclared vars.
- Root keywords that relate properties to each other (`if`/`then`/`else`, `allOf`,
  `anyOf`, `oneOf`, `not`, `dependentRequired`, `dependentSchemas`) leave the chart
  projection and are evaluated by the full-document pass only. The UI's client-side
  chart validation follows the same split.
- A full-document failure is reported by location (`vars.<KEY>` or
  `user_values_json.<path>`) and failed constraint, never with a value. It answers 409
  on the deployment endpoints and 400 on the vars API, matching each endpoint's
  existing schema-failure status.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-vars-schema-routing`: the chart projection no longer carries the root's
  cross-property keywords, and the full submission is validated against the whole
  schema in addition to the two projections.
- `deployment-vars-api`: the never-echo-a-value guarantee covers full-document failures,
  which can be triggered by a var write against stored chart values.

## Impact

- `api/app/services/template_values.py` (projection derivation, new full-document
  validation), `api/app/services/vars.py` (every var write runs it),
  `api/app/services/deployments.py` (create and update ask for 409).
- Endpoint docs for deployment create/update and the vars API.
- `ui/src/components/UserValuesForm.tsx`: the client-side chart projection drops the
  same keywords, so the form no longer refuses what the platform accepts.
- No migration, no catalog change: no current catalog schema uses a root keyword the
  projections do not already apply. The `freepod` CLI does no schema validation and
  needs no change.
