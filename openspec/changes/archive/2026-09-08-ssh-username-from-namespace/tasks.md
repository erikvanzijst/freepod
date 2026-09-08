## 1. Constrain the namespace

- [x] 1.1 Add an Alembic migration that first checks for duplicate `namespace` values and raises with them listed, then creates an unconditional unique index `uq_deployment_namespace`, then drops `uq_deployment_ns_name_active`; verify `alembic upgrade head` succeeds on a seeded database and that the downgrade restores the previous index set
- [x] 1.2 Update `DeploymentORM.__table_args__` in `api/app/models/core.py` to match: unique `Index("uq_deployment_namespace", "namespace")` with no predicate, and `uq_deployment_ns_name_active` removed; verify the suite's migrate-then-compare startup reports no model/migration drift
- [x] 1.3 Add a migration test alongside `api/tests/test_migration_*.py` asserting the pre-flight check fails with the duplicate namespaces named when the table already holds two rows sharing one; verify the test passes
- [x] 1.4 Add model tests asserting two rows with the same namespace are rejected whether the second is active or deleted, and that two rows sharing a `name` across different namespaces are accepted; verify both pass

## 2. Name the environment

- [x] 2.1 Add `environment: str = "dev"` to `CaelusSettings` in `api/app/config.py`; verify a settings test asserts the default and that `CAELUS_ENVIRONMENT` overrides it
- [x] 2.2 Add an `environment` variable to the `caelus` Terraform module and pass `local.environment` to it from `tf/app/main.tf`; verify `terraform plan` in both workspaces shows the variable resolving to `prod` and `dev` respectively
- [x] 2.3 Add `CAELUS_ENVIRONMENT = var.environment` to `tf/app/caelus/configmap.tf`; verify `terraform plan` shows the ConfigMap entry and the rollout annotation checksum changing

## 3. Generate a namespace an operator can read

- [x] 3.1 Change `generate_deployment_namespace` in `api/app/services/reconcile_naming.py` to take the product name alongside the email and build `{slugify(product)[:20]}-{slugify(local_part)[:10]}-{random9}`, reusing `_trim_base` for both segments and raising if the result is not a valid DNS label; update `MAX_NAMESPACE_LEN` to 41
- [x] 3.2 Add unit tests for the formula covering a normal case, over-long product and local part, a local part with `+`/`.`, a segment that slugifies to nothing (falls back rather than doubling a hyphen), absence of the email domain in the output, and the 41-character bound; verify they pass
- [x] 3.3 Add a bounded regeneration loop (5 attempts) in `create_deployment` in `api/app/services/deployments.py` that selects a free namespace before the `DeploymentORM` is built, raising a platform error on exhaustion; verify a test that pre-seeds a colliding namespace still creates the deployment, with a different namespace, and that a test forcing every candidate to collide fails without writing a row

## 4. Address deployments by their id

- [x] 4.1 Change `get_sftp_credentials` in `api/app/services/deployments.py` to `username=str(deployment.id)`, and correct the `SftpCredentialsRead` docstring; verify the SFTP credentials API test asserts the id and rejects both the name and the namespace
- [x] 4.2 Change `resolveQuery` in `ssh-auth/resolve.go` to match `d.id = $1::uuid`, remove `LIMIT 1`, parse the presented username as a uuid before querying, and replace the comment conceding the `deployment.name` uniqueness wart; verify the Go resolver tests pass
- [x] 4.3 Add resolver tests covering: an id admits its deployment; the release name and the namespace are both refused as `unknown_username`; a username that is not a uuid is refused without the store being consulted; a well-formed id naming nothing is refused; the upstream username returned is still the release name and the host is still `{name}-ssh.{namespace}.svc`; verify all pass
- [x] 4.4 Check `ssh-auth/convention_test.go`, which pins the Service name against the host expression; verify it still holds, since the host expression does not move

## 5. Present the id from the client

- [x] 5.1 Change the CLI's SSH username to the deployment's id, taken from the record the client already fetches, through the single helper all four commands use; verify `cli/tests/test_ssh.py` and `test_copy.py` assert the id in the assembled argv
- [x] 5.2 Add a CLI test asserting all four commands (shell, database forward, database session, copy) present the same username for one deployment; verify it passes

## 6. Documentation and sweep

- [x] 6.1 Correct the `cli-ssh-access` main spec's Purpose, which states the username is the deployment name (delta specs do not carry Purpose; edit `openspec/specs/cli-ssh-access/spec.md` directly)
- [ ] 6.2 Grep the repo for prose describing the SSH username as the deployment or release name, and correct each; verify no occurrence remains that contradicts the shipped behavior
- [x] 6.3 Run the full API suite, the Go resolver tests, and the CLI suite; verify all pass

## 7. Cutover

- [x] 7.1 Announce the username change to existing deployment owners before deploying task groups 4 and 5, since the failure mode at the edge is an undiagnosable `Permission denied (publickey)` (see design.md — Risks)
- [x] 7.2 Deploy the API and resolver changes together as one cutover, then the CLI release; verify a live connection using the username the credentials endpoint reports succeeds, and that the old name-based username is refused
