## 1. Vars on create and update

- [x] 1.1 Add a shared parser for vars input in `api/app/cli.py`: `--vars-json` or `--vars-file` (`-` reads stdin), YAML or JSON in the wire shape, validated by `VarsWrite` (design D1, D2)
- [x] 1.2 Pass the parsed vars to `DeploymentCreate.vars` in `create-deployment`, and verify a test creating a deployment of a template with a required sensitive var stores it sensitive and snapshots it into the first release
- [x] 1.3 Pass them to `DeploymentUpdate.vars` in `update-deployment`, and verify a test asserting the var is written with the update

## 2. The `var` command group

- [x] 2.1 Add `caelus var list|get|set|rm USER_ID DEPLOYMENT_ID` with `--phase` (default `runtime`), guarded self-or-admin and resolving the deployment scoped to the user (design D3); move the phase and deleting-deployment checks from `app/api/vars.py` into `app/services/vars.py` so both surfaces share them
- [x] 2.2 `set`: `KEY=VALUE` pairs, a bare `KEY` prompted without echo, `--secret`, `--file` (`-` reads stdin) and `--replace`, through `vars_service.write_vars`
- [x] 2.3 Verify tests: a sensitive var is listed without its value; `rm` deletes; `--replace` deletes absent keys; a reserved key fails with the API's message and writes nothing; an unknown phase and a mismatched user both fail; the write is attributed to the operator

## 3. Verify

- [x] 3.1 Run the full `api/` suite
- [x] 3.2 On dev, create a BookStack or Docmost deployment end to end with the CLI alone, supplying the password on stdin
