## Why

The `caelus` operator CLI has no way to read or write a deployment's vars:
`create-deployment` and `update-deployment` accept only chart values, and there
is no vars command. Any curated product whose template declares a required
runtime var — BookStack's, PhotoPrism's, Lemmy's and Docmost's owner passwords
— therefore cannot be deployed from the CLI at all; the template rejects the
create for the missing var, and passing it as a chart value is refused by the
chart projection. Operators fall back to hand-built REST calls from inside the
API pod. That breaks the platform's API/CLI lockstep convention, which the
vars design itself names as a goal ("one channel … used by both the CLI and
the UI").

## What Changes

- `caelus create-deployment` and `caelus update-deployment` accept vars in the
  one wire shape (`{"vars": {KEY: {value, sensitive}}}`) through `--vars-json`
  or `--vars-file`, where `-` reads standard input so a secret need not appear
  on a command line. They reach the same service fields the REST bodies fill.
- A new `caelus var` command group mirrors the vars endpoints:
  `list`, `get`, `set` (merge, or replace with `--replace`) and `rm`, each
  addressed by user, deployment and an optional `--phase` (default `runtime`).
  `set` takes `KEY=VALUE` pairs, a bare `KEY` to be prompted for without echo,
  and `--secret` to store the given vars write-only.
- Every command goes through `app/services/vars.py`, so validation, the
  sensitive-value rules, reserved keys, limits and error messages are the
  REST API's, unchanged. A sensitive value is never printed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-vars-api`: adds an **Operator CLI parity** requirement, in the
  form `ssh-key-api` and `database-credentials-api` already state theirs, and
  a requirement that the CLI keeps secret values off the command line.

## Impact

- `api/app/cli.py`: new options on `create-deployment` and `update-deployment`,
  and the `var` command group.
- `api/app/services/vars.py`: gains the phase and deleting-deployment checks the
  vars routes made inline, so the CLI shares them; `api/app/api/vars.py` calls
  them. No REST behavior, model or migration changes.
- `api/tests/`: CLI tests for the new options and commands.
- `AGENTS.md`: none; the lockstep convention already covers it.
