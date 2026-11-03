# Tasks

## 1. Full-document validation

- [x] 1.1 Drop the cross-property root keywords from the chart projection
  (`derive_projections`); verify with a test that a root `if`/`then` is absent from it
- [x] 1.2 Add `validate_document()`: merge chart values and coerced vars, validate
  against the schema without its root key-set keywords, report the failing path and
  keyword (plus a `required` failure's missing key) only, raised with no chained
  `ValidationError`; verify with unit tests for a cross-half conditional,
  `dependentRequired`, coercion, an open vars half and the key-set keywords
- [x] 1.3 Prove no value leaks: a sensitive var failing a cross-half rule is absent
  from the message, the exception chain, the formatted traceback and the logs
- [x] 1.4 Raise `validate_vars` failures without chaining the `ValidationError`; verify
  with a test that the formatted traceback carries no value

## 2. Every write path

- [x] 2.1 Run the check in `vars.write_vars` against the deployment's stored or
  just-written chart values and its desired template, with a caller-chosen exception;
  verify via the vars API (`PATCH`, `PUT`, `DELETE`) returning 400
- [x] 2.2 Pass `IntegrityException` from deployment create and update; verify create,
  a chart-only update, an update relying on a stored sensitive var, and an
  administrator's template move, each returning 409 when refused and leaving no
  release behind
- [x] 2.3 Correct the create, update and vars endpoint error documentation

## 3. Compatibility

- [x] 3.1 Confirm no `products/catalog` schema uses a root keyword the projections do
  not already apply, so none is newly refused (a one-time check, not a lasting test)
- [x] 3.2 Mirror the keyword split in the UI's client-side chart projection; verify
  with a `UserValuesForm` test that a cross-half conditional no longer blocks the form

## 4. Conditional fields in the deploy form

- [x] 4.1 Add `schemaConditionals.ts`: evaluate root `if`/`then`/`else`, `allOf` entries
  of those and `dependentRequired` with the form's Ajv instance; verify with unit tests
  for hide/show, `else`, `allOf`, `dependentRequired`, root-required properties and
  typed values
- [x] 4.2 In `UserValuesForm`, evaluate against the document the form would submit,
  render only shown fields, mark conditionally required ones, and submit no hidden
  field; verify with tests for toggling, required marking and the submitted payloads
- [x] 4.3 Verify the Edit dialog sends no entry for a stored var whose field is hidden
- [x] 4.4 Verify the admin template preview re-evaluates on editor changes and on
  toggles in the preview
- [x] 4.5 Give the `admin-schema-preview` main spec the `## Purpose`/`## Requirements`
  structure and the scenario it lacked, so its delta can archive; verify with
  `openspec validate admin-schema-preview --type spec --strict`

## 5. Integration

- [x] 5.1 Run the full api suite, the full UI suite, and the UI type check and build
  green
