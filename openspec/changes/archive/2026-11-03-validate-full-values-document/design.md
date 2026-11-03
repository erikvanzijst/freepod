## Context

`derive_projections()` splits a template schema into a chart projection and a vars
projection; `validate_user_values()` and `validate_vars()` check each half against its
own. The chart projection inherits every root keyword other than `properties` and
`required`, so a root `if`/`then` is evaluated against chart values alone and cannot
see a var (proposal.md, Why).

Vars are stored encrypted, one append-only row per change (`deployment_var`, under the
var keyring). Every write — deployment create, deployment update, and the vars API's
`PATCH`, `PUT` and `DELETE`, through REST and the `caelus` CLI alike — goes through
`vars.write_vars()`, which already decrypts head to compute the resulting set and
validates it against the vars projection of the deployment's desired template.

## Goals / Non-Goals

**Goals:**
- Root conditionals and combinators spanning chart values and vars are evaluated
  against both.
- No current template refuses anything it accepts today.
- No var value reaches an error message, a log line or an exception chain.
- The deploy form shows a conditional field only while its condition applies, and
  marks it required when an applying branch requires it.

**Non-Goals:**
- Client-side full-document validation in the UI: the form shows and requires
  fields; the platform validates.
- Conditionals beyond the subset in D8 in the form, and conditionals below the root.
- Re-checking the full document at reconcile time.

## Decisions

### D1. Cross-property keywords leave the chart projection

`allOf`, `anyOf`, `oneOf`, `not`, `if`, `then`, `else`, `dependentRequired`,
`dependentSchemas` (and draft-7 `dependencies`) are dropped from the chart projection
and evaluated by the full-document pass only.

Adding the full pass alone would not fix the motivating case: the chart pass would
still evaluate the `then` against chart values and refuse. Splitting each conditional
into per-half pieces is not possible in general (an `if` on a chart value with a `then`
on a var has no per-half meaning). For a rule touching chart values only, the full pass
gives the same answer the chart pass did, because var keys never collide with chart
keys; only the error's wording changes (D5).

### D2. The projections own which keys each half may hold

The full pass validates against the schema without its root `additionalProperties`,
`unevaluatedProperties`, `patternProperties`, `propertyNames`, `minProperties` and
`maxProperties`. These describe the set of keys, and each projection already applies
them to its own half: the chart projection keeps the root's, the vars projection's
openness is `x-caelus-vars-additional`. Keeping them in the full pass would refuse every
`custom` deployment with vars (root `additionalProperties: false`, open vars half), and
would make `maxProperties` count var keys it never counted before.

Alternative considered: rewrite the root `additionalProperties` to admit the submitted
var keys. Equivalent for `additionalProperties`, but each other key-set keyword would
need its own rewrite, and the result would still only restate what the projections
enforce.

Key-set keywords nested inside a root applicator are left alone: they are the template
author's to get right, and no catalog template has any.

### D3. The check runs where the resulting state exists: `write_vars`

`write_vars()` gains a `document_error` parameter and runs `validate_document()` right
after the vars projection check, with the resulting head (plaintext, in-process only)
and the deployment row's `user_values_json` as it stands in the transaction, against
the deployment's desired template:

- **create**: the row was just added with the submitted values;
- **update**: called after the guarded `UPDATE`, which the ORM synchronizes onto the
  instance, so it sees the new values and, for a move, the target template;
- **vars API**: the stored chart values.

One call site covers every path, including future ones, and needs no second decryption
of stored vars: `write_vars` already holds the plaintexts it is about to re-encrypt or
compare. A deployment update that says nothing about vars still calls `write_vars`, so
a chart-only change is checked against the stored vars.

### D4. Status follows the endpoint

`document_error` is `IntegrityException` (409) from the deployment create and update
paths — the status their chart-value schema failures already return — and
`ValidationException` (400) from the vars API, its status for every schema failure.

Alternative considered: 409 on the vars API too, since the refusal may stem from stored
chart values. Rejected: the vars API has one status for "these vars do not satisfy the
template", and a caller cannot tell which of the two halves a cross-half rule blames
any better from the status than from the message.

The `freepod` client's release-conflict reader does not recognize the new wording and
falls through to "the platform refused the release: <detail>", not marked retryable,
which is the right reading. No client change.

### D5. Errors name a location and a keyword, never a value

`jsonschema`'s messages embed the instance (`'hunter2' is too short`), and the full
document contains var values. The error is built from the failing path and keyword
only, with the same shape `validate_vars` uses: `vars.<KEY>: failed constraint "<kw>"`
or `user_values_json.<path>: failed constraint "<kw>"`. For `required`, the missing
key, taken from the schema rather than the instance, is appended, so the message points
at the field to fill. The prefix is what is cheap to know: `vars.` for a submitted var
or a declared runtime property, `user_values_json.` for a declared chart property, and
none for anything else (an undeclared key a rule demands). A failure with no path is
reported as `values: failed constraint "<kw>"`.

The exception is raised after the `except` block, so the `ValidationError` holding the
value is attached neither as `__cause__` nor as `__context__`. `validate_vars` raises
the same way: the operator CLI logs a failed command's traceback, and a chained cause
would print the value there.

The UI already routes a `vars.`-prefixed error to its field, and falls back to the
server's message for a `user_values_json` error its own check does not reproduce.

### D6. The reconciler keeps re-checking the chart projection only

The reconciler re-validates chart values before applying a release. It changes no
state, so the full pass already ran for whatever it applies; running it there would
mean decrypting vars in the worker for no new guarantee.

### D7. The UI mirrors the projection split

`UserValuesForm`'s client-side chart projection drops the D1 keywords, so the form
does not refuse a launch the platform would accept. It does not validate the full
document: the platform's error names the field.

### D8. The deploy form derives visibility from the conditionals

Fields stay declared in the root `properties`, which is what routes them, so the form
cannot learn visibility from where a property is declared. It learns it from the
branches that mention it (`schemaConditionals.ts`):

- **Branches read**: the root `if` with its `then`/`else`; the same inside each root
  `allOf` entry; and each root `dependentRequired` entry, as a branch requiring its
  dependents that applies while its trigger is present. `anyOf`, `oneOf`, `not`,
  `dependentSchemas` and anything below the root are not read: they still hold on the
  platform (D1), but the form does not change shape for them.
- **Mentions**: a branch mentions the root properties its `required` names and its
  `properties` declares.
- **Shown**: a root property no branch mentions is always shown; one some branch
  mentions is shown only while a branch mentioning it applies. A property the root
  `required` names is always shown, since hiding it could only produce a refused
  submission. A hidden object property hides every field under it.
- **Required**: the root `required` (as before), plus the properties an applying
  branch's `required` names.
- **Evaluating `if`**: with the form's Ajv 2020-12 instance, the validator it already
  uses for chart values, against one document: the chart values and the vars the form
  would submit, vars typed as the platform coerces them. A stored sensitive var's value
  is unknown to the form, so an `if` reading one sees it absent. An `if` Ajv cannot
  compile is treated as not holding.

Alternative considered: a hand-written matcher for the common `const` case. Rejected:
it would drift from what the platform evaluates the moment a template used `enum`,
`pattern` or `minimum` in an `if`.

A hidden field keeps its value in the form, so toggling a condition back restores
what was typed, but it is submitted in neither half. Vars merge on update, so a hidden
var that is stored stays exactly as stored: hiding sends no entry, never a deletion. A
hidden chart value is dropped from `user_values_json`, which an update replaces whole.

The admin template preview renders the same component from the schema in the editor,
so it re-evaluates on every valid edit and on every change made in the preview itself.

## Risks / Trade-offs

- [A database-authored template with a root applicator over chart keys reports
  failures in the new wording] → Same acceptance as before (D1); the location and
  keyword still name the field.
- [A deployment whose stored state predates a cross-half rule] → Templates are
  immutable versions and a move to a new one is checked (D3), so no deployment can come
  to violate a rule without a refused write. No catalog template declares one today.
- [The full pass is weaker than the old chart pass for D1 keywords at reconcile time]
  → Only for state written before this change; every write since is checked in full.

## Migration Plan

No data migration. Deploy the API and the UI; a template may declare a cross-half rule
once both are live. Rollback is a revert: templates with such a rule are then refused
as before.
