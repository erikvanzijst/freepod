## Why

The SSH username is `deployment.name`, and the resolver looks a deployment up by it. Nothing
makes that name unique. The schema's only guarantee is a partial unique index on
`(namespace, name)` for non-deleted rows; `name` alone is unique by nothing, which the
resolver concedes in a comment beside a `LIMIT 1` that keeps an ambiguous lookup merely
deterministic. Two deployments sharing a name is a coin flip over whose deployment a
connection opens.

The identifier the edge admits has to be one that identifies a deployment among all
deployments, permanently, because it is presented before any deployment context exists. The
deployment's `id` already is that and nothing else in the row is: it is the primary key,
generated as a uuid4, immutable, and never reissued.

`namespace` is not a candidate for a second reason. It names the Kubernetes namespace the
deployment runs in — where it lives, not which one it is. Publishing it would make the
cluster's layout a compatibility surface, so that renaming or re-pooling namespaces could
not be done without breaking every client holding one.

Separately, `namespace` is not enforced unique either, and should be. It is generated per
deployment with no collision check and no constraint behind it, so two deployments could be
placed in one Kubernetes namespace — the isolation boundary the platform relies on to keep
tenants apart. Verified against the live migrated schema: `namespace` carries only a plain
`ix_deployment_namespace` btree, and two active deployments with the same namespace and
different names commit without error.

## What Changes

- **BREAKING: the SSH username is the deployment's `id`.** The resolver matches on it, the
  SFTP credentials endpoint reports it, and the CLI presents it. There is no transition
  window — `ssh <name>@freepod.eu` stops resolving the moment the resolver deploys.
- **The username is matched in full.** A prefix of an id, however unambiguous when presented,
  is refused; and a username that is not a well-formed id is refused without querying the
  store.
- **`namespace` becomes unconditionally unique**, over every row including deleted ones, so
  one namespace holds one deployment and a namespace terminating in the cluster cannot be
  claimed by a second. Generation gains a bounded regeneration loop so a collision is
  resolved rather than surfaced.
- **The namespace formula changes** from `{slugify(email)[:20]}-{random9}` to
  `{slugify(product)[:20]}-{slugify(email local part)[:10]}-{random9}`, so a list of
  namespaces says what each one holds and whose it is. Applies to deployments created after
  the change; existing namespaces are immutable and keep their current form.
- **The `(namespace, name)` partial unique index is dropped**, subsumed: one row per
  namespace makes a duplicate pair unreachable.
- **The platform is told which environment it is** (`CAELUS_ENVIRONMENT`), from the value
  Terraform already computes. Nothing derives behavior from it yet; it is the one place the
  distinction is named for whatever needs it.
- **The sidecar's login account is unchanged.** It remains the Helm release name. The edge
  translates the presented username into an upstream account, so the client-facing
  identifier and the account inside the tenant's pod are two separate facts. No chart is
  re-rendered and no deployment is reconciled.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-namespace`: the generation formula changes; the namespace becomes
  unconditionally unique across all rows, with collisions regenerated rather than inserted;
  and the namespace is stated to be internal, addressed by nothing outside the platform.
- `deployment-naming`: the `(namespace, name)` partial unique index requirement is removed as
  subsumed by unconditional namespace uniqueness.
- `ssh-auth-resolver`: the username a client presents is the deployment's id, matched in
  full, and the account presented upstream is the deployment's release name.
- `sftp-credentials-api`: the `username` the endpoint reports is the deployment's id.
- `ssh-chart-contract`: the requirement conflating "the username a deployment is addressed
  by" with the sidecar's login account is split into the two facts it covers.
- `cli-ssh-access`: the client presents the identifier the platform reports for the
  deployment rather than deriving one from another field.
- `pydantic-settings`: settings name the environment the platform is running as.

## Impact

- **Database**: one Alembic migration — add `uq_deployment_namespace` (unconditional), drop
  `uq_deployment_ns_name_active`. The migration must refuse to run if duplicate namespaces
  exist rather than failing on index creation with an opaque error. Current dev data is clean
  (53 rows, 53 distinct namespaces).
- **API** (`api/app/`): `reconcile_naming.generate_deployment_namespace` (formula),
  `services/deployments.create_deployment` (collision loop),
  `services/deployments.get_sftp_credentials` (`username=str(deployment.id)`), the
  `SftpCredentialsRead` docstring, and a new `environment` setting in `config.py`.
- **SSH resolver** (`ssh-auth/`): `resolveQuery` matches `d.id`; the username is parsed as a
  uuid before the query, so a malformed one is a refusal rather than a cast error. The
  upstream host stays `{name}-ssh.{namespace}.svc` and the upstream username stays `d.name`.
  The comment admitting the `deployment.name` uniqueness wart and its `LIMIT 1` both go.
- **CLI** (`cli/`): one helper all four commands take the username from. `.freepod.json` is
  unaffected — it records the deployment's id already, and the client reads the identifier
  from the deployment record the platform returns.
- **Terraform** (`tf/app/`): a variable on the `caelus` module and one `CAELUS_ENVIRONMENT`
  entry in `caelus/configmap.tf`, from the existing `local.environment`.
- **UI** (`ui/`): the SFTP fields render whatever the credentials endpoint reports, so no
  component logic changes; the file-access dialog widens to `sm` because a 36-character
  username does not fit the narrower one, which also matches the database dialog beside it.
- **Users**: every existing SSH invocation, `known_hosts` entry keyed on the username, and
  saved SFTP client profile breaks at cutover.
