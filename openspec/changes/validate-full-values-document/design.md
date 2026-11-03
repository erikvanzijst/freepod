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

**Non-Goals:**
- Rendering conditionals in the deploy form (`UserValuesForm` renders a flat field
  list). The form submits; the platform's error names the field.
- Client-side full-document validation in the UI.
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
or `user_values_json.<path>: failed constraint "<kw>"`. For `required` and
`dependentRequired`, the missing key, taken from the schema rather than the instance,
is appended, so the message points at the field to fill. A path's first segment picks
the channel: a declared property by its routing marker, an undeclared one as a var when
it was submitted as one or the vars half is open.

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
does not refuse a launch the platform would accept. It does not evaluate the full
document: the platform's error names the field.

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
