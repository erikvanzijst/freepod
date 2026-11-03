# Tasks

## 1. Full-document validation

- [x] 1.1 Drop the cross-property root keywords from the chart projection
  (`derive_projections`); verify with a test that a root `if`/`then` is absent from it
- [x] 1.2 Add `validate_document()`: merge chart values and coerced vars, validate
  against the schema without its root key-set keywords, report location and keyword
  only, raised with no chained `ValidationError`; verify with unit tests for a
  cross-half conditional, `dependentRequired`, coercion, an open vars half and the
  key-set keywords
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

- [x] 3.1 Verify every `products/catalog` schema uses no root keyword the projections
  do not already apply, and accepts representative valid input through all passes
- [x] 3.2 Mirror the keyword split in the UI's client-side chart projection; verify
  with a `UserValuesForm` test that a cross-half conditional no longer blocks the form
- [x] 3.3 Run the full api suite and the UI tests green
