# Tasks

## 1. `custom` chart accepts string owner ids

- [ ] 1.1 In `products/custom/chart/values.schema.json`, type `caelus.owner.id` as `["integer", "string"]`. In `templates/_helpers.tpl`, relax the repository assertion from `^[0-9]+$` to `^[0-9a-z]{1,12}$` and reword its failure message. Bump the chart version. Verify with `helm template` that `owner.id: 42` + `image: 42@sha256:…` and `owner.id: "k7m2qx9d4hfa"` + `image: k7m2qx9d4hfa@sha256:…` both render, and that a mismatched owner, an uppercase repository and a 13-character repository each fail.
- [ ] 1.2 Add chart-rendering tests for the 1.1 cases to the API suite (they join conftest's `helm_charts` xdist group), and point the catalog's `custom` template at the new chart version. Verify the chart tests pass and `catalog apply --dry-run` shows only the version change.

## 2. Schema and model

- [ ] 2.1 Add a `new_user_id()` generator: 12 characters from `secrets.choice` over the shared base36 alphabet, redrawn when all digits. Unit-test the length, alphabet and all-digit rejection by forcing an all-digit draw with a patched `secrets.choice`. Verify the tests pass.
- [ ] 2.2 Change `UserORM.id` to `str` with `default_factory=new_user_id`. Change the four referencing columns (`DeploymentORM.user_id`, the subscription `user_id`, `UserSshKeyORM.user_id`, `VarORM.created_by`) to `str`/`String(12)`. Update the read and write models (`UserRead`, `DeploymentBase`/`Create`/`Update`, subscription and usage reads, `VarWriter`). Verify that `alembic check` against the migrated test DB (2.3) reports no drift.
- [ ] 2.3 Write the Alembic migration per design D5:
  - Look up the FK names in `pg_constraint`, drop them, convert the five columns `USING …::text`, then recreate the FKs with their `ON DELETE` behavior.
  - Drop the default and `user_id_seq`, and add `CHECK (id ~ '^[0-9a-z]{1,12}$')`.
  - Make `downgrade()` raise `NotImplementedError`.

  Verify on a copy of a seeded DB that ids `1..n` become `'1'..'n'`, that all FK relationships survive, and that an insert with no id, an uppercase id or a duplicate id is rejected.

## 3. API surface

- [ ] 3.1 Change every `user_id`/`owner_id` annotation from `int` to `str` across `api/app` (routes, services, `deps.require_self`, the usage report and the `user_id` query filter, `network_policy.deployment_namespace_labels`, the operator CLI). Remove `int(user_id)` from `artifacts.py`. Verify with `grep -rnE "(user|owner)_id: (Optional\[)?int|int\((user|owner)_id"` over `api/app` that nothing is left.
- [ ] 3.2 In `registry_tokens.py`, change `_PULL_USERNAME` to `pull-([0-9a-z]{1,12})` and drop the `int()` parse. Verify with tests that a legacy account's existing pull credential still verifies byte for byte (fixed HMAC key, id `"42"`, compared against a literal computed from the pre-change code) and that a new account's credential verifies and is scoped to `u/<id>`.
- [ ] 3.3 In `reconcile._build_owner_overrides`, project `owner.id` as `int` when the id is all digits and as the string otherwise (design D6). Verify with tests covering both branches.
- [ ] 3.4 Order `services.users.list_users` by `created_at`. Verify with a test that lists accounts in creation order regardless of id.
- [ ] 3.5 Update test fixtures in `api/tests/conftest.py`. The default regular user gets a generated non-numeric id. Keep explicit legacy-id fixtures (e.g. `"5"`, `"7"`) only where a test exercises D2 or D6. Update the integer user-id literals throughout the suite. Add tests for the `user-identifier` scenarios: `GET /api/me` returns a string `id`, `/api/users/042/…` is refused for account `"42"`, and the admin usage filter works with a new id. Update the `require_self` tests to the `authorization-guards` delta. Verify that the full `api/` suite passes with `-n 8`.

## 4. Go daemons

- [ ] 4.1 Update the `daemons/ssh-auth` and `daemons/app-auth` test fixtures to insert string user ids, using both a legacy-numeric and a generated id. Verify that `go test ./...` passes in both daemons against the migrated test DB.

## 5. Clients

- [ ] 5.1 In the UI, change `userId: number` → `string` in `ui/src/api/types.ts` and `ui/src/api/endpoints.ts`, and fix every caller the compiler reports. Change `AdminUsagePanel` to read its `user` query parameter as a string (drop the `/^\d+$/` check and `Number()`). Verify that `npm run build` and the UI tests pass, and that the admin usage panel filters by a non-numeric id in the dev UI.
- [ ] 5.2 In the CLI, change the `user_id: int` hints to `str`. Behavior is unchanged. Verify that the `cli/` test suite passes, and that a released `freepod` version runs `whoami`, `deploy` and `log` against the dev API with an account that has a non-numeric id.

## 6. Integration

- [ ] 6.1 Run the migration on dev. Verify that an existing account's deployments, SSH keys, vars, builds and image pulls are unaffected, and that a newly created account gets a 12-character base36 id and can complete a `freepod deploy` of a `custom` app end to end (build pushed to `u/<id>`, image ownership assertion passes, pod pulls).
- [ ] 6.2 On dev, roll an existing custom deployment back to a release on the previous `custom` chart version. Verify that it renders and rolls out (D6).

## Workflow follow-up

- Prod rollout follows the design's Migration Plan: publish the chart first, then the API and UI.
- Archive the change after review and the prod rollout, syncing the delta specs. The `authorization-guards` main spec still carries the non-conformant `## ADDED Requirements` header. Fix it to `## Requirements` before archiving.
