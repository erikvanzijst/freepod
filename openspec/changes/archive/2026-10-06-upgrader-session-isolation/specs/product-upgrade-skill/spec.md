## RENAMED Requirements

- FROM: `### Requirement: A dry run changes nothing on GitHub`
- TO: `### Requirement: No session changes anything on GitHub`

## MODIFIED Requirements

### Requirement: No session changes anything on GitHub
A session MUST NOT write to GitHub, in a dry run or a real run. It MUST NOT push a branch,
create a label, open or comment on a pull request, or wait on CI. It MUST commit locally
on `upgrade/<slug>-<target_version>`, because the patch it proposes is built from those
commits. In a real run, the runner publishes the proposal (`product-upgrade-runs`).

`UPGRADE_DRY_RUN` changes one thing in a session: what a duplicate check does. In a real
run a duplicate check stops the session, which records `skipped`. In a dry run it MUST
NOT stop the session. The session records the reason a real run would have skipped and
carries on with every remaining step.

When nothing is left to do, a dry run MUST record `skipped`, as a real run would. An
upstream source that cannot be reached is such a case: without its releases there is no
target to review.

#### Scenario: A dry run finds a newer release
- **WHEN** a session, in a dry run or a real run, finds a newer eligible release for its product
- **THEN** no branch, label or pull request is created on GitHub by the session
- **AND** the output directory holds the proposed pull request's title, description and patch

#### Scenario: A real run meets a duplicate check
- **WHEN** a real-run session finds an open pull request that already sets the product's target version
- **THEN** `result.json` has `status` `skipped`, with a `skip_reason` naming that pull request

#### Scenario: A dry run meets a duplicate check
- **WHEN** a dry run finds an open pull request that already sets the product's target version
- **THEN** the session still writes the proposed pull request's description and patch
- **AND** its result records that a real run would have skipped the product, and why

#### Scenario: A dry run cannot reach the upstream source
- **WHEN** a dry run cannot fetch the releases or tags of its product's upstream source
- **THEN** `result.json` has `status` `skipped`, not `would_skip`, with a `skip_reason` naming the source
- **AND** no proposed description or patch is written

### Requirement: Every session writes a machine-readable result
Before it ends, every session MUST write `result.json` to `$UPGRADE_OUT_DIR/<slug>/`, in
real runs and dry runs alike. The file MUST hold a single JSON object with these fields:

- `schema_version`: `2`.
- `product`: the slug.
- `dry_run`: a boolean.
- `status`: one of `up_to_date`, `would_open`, `skipped`, `would_skip` or `failed`. A
  session never writes `opened`: only the runner opens a pull request.
- `current_version`: the value at the product's `version_path` on `master`.
- `target_version`: the newest eligible release under the version-jump policy, or `null`
  when nothing newer exists.
- `draft`: whether the pull request should be a draft.
- `branch`: `upgrade/<slug>-<target_version>`. Present for `would_open` and `would_skip`.
- `skip_reason`: why a pull request should not be opened. Required for `skipped` and
  `would_skip`.
- `needs_human`: a list of the decisions a human has to make, empty when there are none.
- `error`: what went wrong. Required for `failed`.

When `status` is `would_open` or `would_skip`, the same directory MUST also hold:

- `body.md`: the exact pull request description;
- `change.patch`: the session's commits, as `git format-patch --stdout origin/master..HEAD`;
- `meta.json`: an object with `title`, which is `<Product>: Upgrade to <target_version>`,
  and, for `would_skip` only, `would_skip`, the reason.

The runner publishes `would_open` from exactly these files. The labels, base branch and
branch name are fixed by the runner, not taken from the session.

`body.md` MUST NOT link to a GitHub issue or pull request, and MUST NOT @-mention anyone
(`Changelog sanitization`).

When `UPGRADE_RUN_URL` is set, `body.md` MUST end with a link to it, so that a reviewer
reading the pull request reaches the session that wrote it: its transcript, its result
files and its patch. It MUST be that link and not one to a stored file, because a signed
file link expires within the hour while a pull request is read long after. When the
variable is empty the description MUST carry no such link.

The prose run report stays in the session's final message for a human to read. A runner
MUST NOT depend on it.

#### Scenario: The product is up to date
- **WHEN** no eligible release is newer than the product's current version
- **THEN** `result.json` has `status` `up_to_date` and `target_version` `null`
- **AND** no `body.md`, `change.patch` or `meta.json` is written

#### Scenario: A real run opens a draft
- **WHEN** a real-run session proposes a pull request that should be a draft because the major version changes
- **THEN** `result.json` has `status` `would_open`, `draft` `true`, and the branch in `branch`
- **AND** `needs_human` names each decision listed in the description's *Needs human review* section
- **AND** `body.md`, `change.patch` and `meta.json` are written beside it

#### Scenario: A dry run would open a pull request
- **WHEN** a dry run finds a newer release and no duplicate check applies
- **THEN** `result.json` has `status` `would_open`, the proposed branch in `branch`, and no `pr_url` field

#### Scenario: The description leads back to the run
- **WHEN** a session writes `body.md` while `UPGRADE_RUN_URL` is set
- **THEN** the description ends with a link to that URL

#### Scenario: A real run skips the product
- **WHEN** a real-run session finds that an image the chart needs does not exist at the target tag
- **THEN** `result.json` has `status` `skipped` and a `skip_reason` naming the missing image

#### Scenario: The session cannot finish
- **WHEN** a session cannot complete the procedure for a reason the skill does not treat as a skip
- **THEN** `result.json` has `status` `failed` and an `error` saying where the session stopped
