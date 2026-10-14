## Context

The vars REST surface (`app/api/vars.py`) and the `vars` fields on
`DeploymentCreate` / `DeploymentUpdate` are thin over `app/services/vars.py`
and `app/services/deployments.py`, which already do all validation, encryption
and history. The operator CLI (`app/cli.py`) exposes none of it.

## Goals / Non-Goals

**Goals:**

- Every vars operation the API offers, from the CLI, through the same services.
- A secret can be supplied without appearing on a command line.

**Non-Goals:**

- Any change to the REST API's behavior or the wire shape. The two checks the
  vars routes made themselves, an unknown phase and a deployment being deleted,
  move into `app/services/vars.py` so both surfaces share them.
- Rolling a deployment out after a var write. As over REST, a write stages the
  vars and `pending` reports the difference; `update-deployment` applies them.

## Decisions

### D1. One wire shape in, YAML out

`--vars-json` / `--vars-file` and `var set --file` take the API's body,
`{"vars": {KEY: {"value": …, "sensitive": …}}}`, parsed as YAML (a superset of
JSON) and validated by the `VarsWrite` model. Reads print the `VarsRead` model as
YAML, like every other CLI read. So the output of `var list` can be fed back to
`var set --replace --file`: the sensitive entries carry no `value`, which the
service already treats as "unchanged", and the read-only fields are ignored by
`VarWrite`.

Alternative: `KEY=VALUE` only. Rejected as the only form because it cannot
express `sensitive: false` on an existing sensitive var, or a round-trip; kept
as the convenient form for `var set`.

### D2. Secrets stay off the command line

A file argument of `-` reads standard input, so an operator can run
`kubectl exec -i … caelus create-deployment … --vars-file - < vars.json`, and
`var set` prompts without echo for a bare `KEY`. `KEY=VALUE` remains available
for non-sensitive values. The CLI never prints a sensitive value because it
prints only what the service's read returns.

### D3. Addressing matches the existing deployment commands

`var` commands take `USER_ID DEPLOYMENT_ID` positionally, as
`get-deployment-database` and `get-deployment-sftp` do. `caelus` has no
`require_self`, so the commands carry the explicit guard `list-releases` uses:
an operator who is not an administrator may name only their own account. The
deployment is then resolved scoped to that user, even for an administrator, so
a mistyped pair is a 404 rather than a write to someone else's deployment. The
acting operator is the writer recorded on each var. `--phase` defaults to
`runtime`, the only phase, and an unknown one fails as the API's 404 does.

## Risks / Trade-offs

- [An operator writes to a tenant's vars] → Already true of every operator
  command and of an admin over REST; the write is attributed to the operator in
  the var's history.
