# deployment-vars-api Specification

## Purpose
Defines the HTTP contract for a deployment's vars: how they are addressed, the single
wire shape used everywhere, the write-only treatment of sensitive values, and the limits
and error behavior that keep a secret from leaking back out. The `caelus` operator CLI
offers the same operations under the same rules.

## Requirements

### Requirement: Vars are addressed by deployment, phase and key
A var's identity is the triple of the deployment that owns it, the **phase** in which it
is consumed, and its key. All three SHALL appear in the path:

- `/api/users/{user_id}/deployments/{deployment_id}/vars/{phase}` — the collection of
  one phase's vars
- `/api/users/{user_id}/deployments/{deployment_id}/vars/{phase}/{key}` — one var

The phase SHALL be a path segment and MUST NOT be a query parameter: two vars may share a
key when their phases differ, so the phase is part of what names the resource rather than
a filter over a set.

The only phase in this capability is `runtime`. The server SHALL reject any other phase
with 404. `{phase}` is a closed vocabulary describing **when a value is consumed**, and
MUST NOT be used for a deployment environment such as `production` or `staging`: those
are a separate axis, already expressed by `{deployment_id}` one segment earlier.

There SHALL NOT be a root-level vars endpoint, and vars SHALL NOT be addressable by any
surrogate identifier — the natural key is the identity.

Reading or writing vars SHALL be permitted only to the deployment's owner and to
administrators, consistent with every other user-owned resource. A request for a
deployment that does not exist or does not belong to the caller SHALL NOT reveal which
of the two it was.

#### Scenario: Owner reads their vars
- **WHEN** the owner requests `.../vars/runtime` for their deployment
- **THEN** the response lists the deployment's runtime head

#### Scenario: Another user reads the vars
- **WHEN** a user who does not own the deployment requests its vars
- **THEN** the request is refused

#### Scenario: A key that does not exist
- **WHEN** a caller requests `.../vars/runtime/NOPE` and head has no such key
- **THEN** the response is 404

#### Scenario: An unknown phase
- **WHEN** a caller requests `.../vars/production` or `.../vars/build`
- **THEN** the response is 404

### Requirement: Vars use one wire shape everywhere
Every request and response carrying vars SHALL use a single shape: an object under a
`vars` key, mapping each var's key to an object with a `value` and an optional
`sensitive` flag. This SHALL be the shape on deployment create and update, on the vars
collection, on a single var, and on a release read.

The map SHALL be nested under `vars` rather than being the top-level object, so that
envelope fields can be added without colliding with a caller-controlled key.

A var's `value` SHALL always be a string on the wire, including for a schema-declared
`boolean`, `integer` or `number`.

#### Scenario: The collection shape
- **WHEN** a caller reads the vars collection
- **THEN** the response body has a `vars` object mapping keys to entry objects
- **AND** it is not a bare map at the top level

### Requirement: A string value is coerced to the schema's declared type before validation
Where the vars projection declares a type for a property, the platform SHALL convert the
submitted string before validating it: `"true"` and `"false"` to a boolean, an integer
literal to an integer, a number literal to a number, and a string unchanged. A value that
cannot be converted SHALL be rejected. The projection's own constraints SHALL then be
applied to the converted value.

The stored value and the value delivered to the pod SHALL be the submitted string, not
the converted form.

#### Scenario: A boolean-typed var
- **WHEN** a caller sets a var declared `boolean` to `"false"`
- **THEN** the value validates as the boolean `false`
- **AND** the pod receives the string `false`

#### Scenario: An uncoercible value
- **WHEN** a caller sets a var declared `boolean` to `"yes"`
- **THEN** the request is rejected

#### Scenario: A constrained string
- **WHEN** a caller sets a var declared `string` with `minLength: 8` to a 3-character
  value
- **THEN** the request is rejected

### Requirement: Reads omit the value of a sensitive var
An entry for a sensitive var SHALL be returned **without its `value` field**. The field
SHALL NOT be present with a masked string, and SHALL NOT be present with a null. No
hash, digest or fingerprint of the value SHALL be returned in its place.

This holds on every read: the vars collection, a single var, a deployment read, and a
release read.

A masked placeholder invites a caller to write it back as the new value. A null is worse,
because null is how a caller deletes a key, so a caller that read and re-submitted a
response would delete every secret it could not read. Omission is unambiguous and makes
a read/modify/write round-trip safe.

#### Scenario: Reading a sensitive var
- **WHEN** a caller reads a var stored as sensitive
- **THEN** the entry reports `sensitive: true` and carries no `value` field

#### Scenario: Reading a non-sensitive var
- **WHEN** a caller reads a var stored as not sensitive
- **THEN** the entry carries its `value`

#### Scenario: Round-tripping a read into a write
- **WHEN** a caller reads the vars collection and submits the response body back
  unchanged
- **THEN** no var is deleted and no value is altered

### Requirement: Writes merge or replace, and an absent value leaves a var unchanged
A `PATCH` of the vars collection SHALL merge: keys present are written, a key whose
`value` is explicitly null is deleted, and keys absent from the body are untouched. A
`PUT` SHALL replace: keys absent from the body are deleted. A `DELETE` of a single var
SHALL delete that key. Both are scoped to the phase named in the path: a `PUT` to one
phase's collection MUST NOT affect any other phase's vars.

In both `PATCH` and `PUT`, an entry whose `value` field is **absent** SHALL mean "leave
this key's value unchanged", which is what makes a read's output safely writable. An
entry that omits `value` and names a key that is not in head SHALL be rejected, since
there is nothing to leave unchanged.

A write MAY change a var's sensitivity without supplying a value, subject to the rules in
`deployment-vars-schema-routing`. Turning a sensitive var into a non-sensitive one SHALL
require a new value.

Deleting a key that is not in head SHALL succeed without recording anything.

#### Scenario: Merging
- **WHEN** a caller PATCHes `{"vars": {"A": {"value": "1"}}}` and head holds `A` and `B`
- **THEN** `A` is updated and `B` is untouched

#### Scenario: Replacing
- **WHEN** a caller PUTs `{"vars": {"A": {"value": "1"}}}` and head holds `A` and `B`
- **THEN** `A` is updated and `B` is deleted

#### Scenario: Deleting through a merge
- **WHEN** a caller PATCHes `{"vars": {"B": {"value": null}}}`
- **THEN** `B` is deleted

#### Scenario: Leaving a sensitive var unchanged
- **WHEN** a caller submits an entry for an existing sensitive var with no `value` field
- **THEN** the var keeps its current value

#### Scenario: Omitting the value of an unknown key
- **WHEN** a caller submits an entry with no `value` field for a key not in head
- **THEN** the request is rejected

#### Scenario: Deleting an absent key
- **WHEN** a caller deletes a key that is not in head
- **THEN** the request succeeds and no tombstone is written

#### Scenario: Making a sensitive var readable again
- **WHEN** a caller sets `sensitive: false` on a sensitive var without supplying a value
- **THEN** the request is rejected

### Requirement: A deployment reports whether its runtime vars differ from what is running
Reads that carry vars SHALL report a `pending` flag: true when the deployment's
**runtime** head differs from the snapshot of its **applied** release, false otherwise. A
deployment with no applied release and a non-empty runtime head SHALL report `pending` as
true.

`pending` SHALL be computed against the applied release and MUST NOT be computed against
the desired release. After a failed rollout head equals the *failed* release's snapshot,
so comparing against the desired release would report nothing pending while the running
pod carries none of the changes.

On a phase-scoped collection the path already fixes what `pending` refers to. On
`DeploymentRead`, which spans the deployment as a whole, the definition above is
deliberately narrow: `pending` means "a rollout would change the running pod's
environment", and it MUST NOT be widened to cover any other kind of staleness. A value
consumed in another phase is compared against a different reference and answered by a
different remedy, so it belongs in a separate, separately-named field rather than in this
one.

#### Scenario: Staged change
- **WHEN** a var is written without a rollout
- **THEN** `pending` is true

#### Scenario: After a successful rollout
- **WHEN** the release carrying the change is applied
- **THEN** `pending` is false

#### Scenario: After a failed rollout
- **WHEN** the release carrying the change fails and the previous release is still the
  applied one
- **THEN** `pending` is true

### Requirement: Administrators get no elevated read of sensitive values
An administrator reading another user's deployment, vars, or releases SHALL receive
exactly what the owner receives, with sensitive values omitted. There SHALL be no
endpoint, parameter, or role that returns a stored sensitive value in plaintext.

A write-only value an operator can read is not write-only.

#### Scenario: Admin reads a tenant's vars
- **WHEN** an administrator reads another user's vars
- **THEN** sensitive entries carry no `value` field

### Requirement: Var keys and sizes are bounded and platform names are reserved
The platform SHALL reject a var whose key does not match
`^[A-Za-z_][A-Za-z0-9_]{0,63}$`, whose value exceeds 8 KiB of UTF-8 plaintext, that
would take the deployment's head above 128 KiB of total plaintext, or that would take it
above 256 keys.

The platform SHALL reject a var whose key begins with `CAELUS_`, `AWS_`, `S3_` or
`RAILPACK_`, or whose key is `BUCKET_NAME` or `PORT`. These are names the platform, or
the build toolchain it is built on, reserves for itself.

Bounds are enforced when the request is handled, so that an oversized or malformed var
fails with a clear error rather than opaquely during a rollout. A Kubernetes Secret has a
1 MiB ceiling that a deployment's vars share with platform-provided credentials.

#### Scenario: An over-long value
- **WHEN** a caller sets a var whose value exceeds 8 KiB
- **THEN** the request is rejected and nothing is stored

#### Scenario: A reserved key
- **WHEN** a caller sets a var named `AWS_SECRET_ACCESS_KEY`
- **THEN** the request is rejected

#### Scenario: A malformed key
- **WHEN** a caller sets a var named `log-level`
- **THEN** the request is rejected

### Requirement: A validation failure never echoes the submitted value
An error returned for an invalid var, and any log line recording it, SHALL identify the
var by key and by the constraint it failed, and MUST NOT include the submitted value or
any part of it.

Schema validation libraries conventionally embed the offending instance in their error
message; that message reaches both the caller and the log aggregator, so it MUST NOT be
propagated for vars.

#### Scenario: A sensitive var fails validation
- **WHEN** a caller sets a sensitive var to a value the schema rejects
- **THEN** the error names the key and the failed constraint
- **AND** neither the response nor any log line contains the submitted value

### Requirement: Operator CLI parity
The `caelus` operator CLI MUST offer every vars operation the REST API offers — reading
the collection and a single var, merging, replacing, deleting one var, and supplying vars
when a deployment is created or updated — in the one wire shape, by calling the same
service layer. Validation, reserved keys, limits and error messages SHALL be the API's,
and a write SHALL be recorded as made by the operator who ran it.

#### Scenario: Deploying a product with a required runtime var
- **WHEN** an operator creates a deployment through the CLI and supplies the template's
  required sensitive var through the vars input
- **THEN** the deployment is created with the var stored as sensitive and included in
  its first release

#### Scenario: An invalid var through the CLI
- **WHEN** an operator writes a reserved key through the CLI
- **THEN** the CLI fails with the API's error for that key, and nothing is written

### Requirement: The operator CLI keeps secret values off the command line
The CLI SHALL let a var's value be supplied without placing it in a command-line
argument — from standard input, or at a prompt that does not echo — since arguments are
visible to other processes and kept in shell history. A CLI read SHALL omit the value of
a sensitive var exactly as an API read does.

#### Scenario: Supplying a secret without a command-line argument
- **WHEN** an operator sets a var through the CLI and provides its value on standard
  input or at a non-echoing prompt
- **THEN** the var is written and the value appears in no argument of the process

#### Scenario: Reading a sensitive var through the CLI
- **WHEN** an operator lists a deployment's vars through the CLI
- **THEN** a sensitive var is reported without its value
