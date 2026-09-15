## Purpose

The upgrade-product skill as a repository artifact. It is the agent instruction set that
takes one curated product from "is there a newer upstream release" to one reviewed pull
request, and it defines the machine-readable result a runner consumes instead of the
agent's prose.

## ADDED Requirements

### Requirement: The skill lives with the products it maintains
The skill MUST be kept at `products/UPGRADING/SKILL.md` on `master`, and a runner MUST
read it from there rather than from a copy of its own.

Product-specific upstream knowledge MUST live in that product's `products/<slug>/README.md`,
under an "Upstream references" section, and not in the skill. That knowledge covers where
the product's release notes are published, which upstream artifacts describe its reference
deployment, and its known upgrade pitfalls.

#### Scenario: A skill change reaches the next session by merging
- **WHEN** a change to `products/UPGRADING/SKILL.md` is merged to `master`
- **THEN** the next session started after the merge follows the changed skill
- **AND** no runner has to be rebuilt or redeployed for it

#### Scenario: A product the skill can upgrade has its references
- **WHEN** a catalog file declares an `upstream` block whose source is not a placeholder
- **THEN** that product's `products/<slug>/README.md` contains an "Upstream references" section

### Requirement: One session handles exactly one named product
A session MUST act on exactly one curated product: the catalog slug in the
`UPGRADE_PRODUCT` environment variable. It MUST NOT change files that belong to any other
product, and it MUST NOT open more than one pull request.

#### Scenario: Only the named product is changed
- **WHEN** a session runs with `UPGRADE_PRODUCT=vaultwarden`
- **THEN** every commit the session makes changes only `products/catalog/vaultwarden.yaml` and files under `products/vaultwarden/`
- **AND** the session opens at most one pull request

### Requirement: A dry run changes nothing on GitHub
When `UPGRADE_DRY_RUN` is `1`, a session MUST perform every step a real run performs
except those that write to GitHub. It MUST NOT push a branch, create a label, or open a
pull request. It MUST still commit locally, because the patch it writes is built from
those commits.

A duplicate check that would stop a real run MUST NOT stop a dry run. The session records
the reason a real run would have skipped and carries on with every remaining step.

When nothing is left to do, a dry run MUST record `skipped`, as a real run would. An
upstream source that cannot be reached is such a case: without its releases there is no
target to review.

#### Scenario: A dry run finds a newer release
- **WHEN** a dry run finds a newer eligible release for its product
- **THEN** no branch, label or pull request is created on GitHub
- **AND** the output directory holds the would-be pull request's description and patch

#### Scenario: A dry run meets a duplicate check
- **WHEN** a dry run finds an open pull request that already sets the product's target version
- **THEN** the session still writes the would-be pull request's description and patch
- **AND** its result records that a real run would have skipped the product, and why

#### Scenario: A dry run cannot reach the upstream source
- **WHEN** a dry run cannot fetch the releases or tags of its product's upstream source
- **THEN** `result.json` has `status` `skipped`, not `would_skip`, with a `skip_reason` naming the source
- **AND** no would-be description or patch is written

### Requirement: Every session writes a machine-readable result
Before it ends, every session MUST write `result.json` to `$UPGRADE_OUT_DIR/<slug>/`, in
real runs and dry runs alike. The file MUST hold a single JSON object with these fields:

- `schema_version`: `1`.
- `product`: the slug.
- `dry_run`: a boolean.
- `status`: one of `up_to_date`, `opened`, `would_open`, `skipped`, `would_skip` or
  `failed`.
- `current_version`: the value at the product's `version_path` on `master`.
- `target_version`: the newest eligible release under the version-jump policy, or `null`
  when nothing newer exists.
- `draft`: whether the pull request is, or would be, a draft.
- `pr_url`: the URL of the opened pull request. Present for `opened` only.
- `branch`: the pull request's branch. Present for `opened`, `would_open` and `would_skip`.
- `skip_reason`: why a real run did not, or would not, open a pull request. Required for
  `skipped` and `would_skip`.
- `needs_human`: a list of the decisions a human has to make, empty when there are none.
- `error`: what went wrong. Required for `failed`.

When a pull request is opened, or would be, the same directory MUST also hold its exact
description as `body.md` and its commits as `change.patch`, in real runs as well as dry
runs.

The prose run report stays in the session's final message for a human to read. A runner
MUST NOT depend on it.

#### Scenario: The product is up to date
- **WHEN** no eligible release is newer than the product's current version
- **THEN** `result.json` has `status` `up_to_date` and `target_version` `null`
- **AND** it has no `pr_url`

#### Scenario: A real run opens a draft
- **WHEN** a real run opens a draft pull request because the major version changes
- **THEN** `result.json` has `status` `opened`, `draft` `true`, and the pull request's URL in `pr_url`
- **AND** `needs_human` names each decision listed in the pull request's *Needs human review* section
- **AND** `body.md` and `change.patch` are written beside it

#### Scenario: A dry run would open a pull request
- **WHEN** a dry run finds a newer release and no duplicate check applies
- **THEN** `result.json` has `status` `would_open`, the would-be branch in `branch`, and no `pr_url`

#### Scenario: A real run skips the product
- **WHEN** a real run finds that an image the chart needs does not exist at the target tag
- **THEN** no pull request is opened
- **AND** `result.json` has `status` `skipped` and a `skip_reason` naming the missing image

#### Scenario: The session cannot finish
- **WHEN** a session cannot complete the procedure for a reason the skill does not treat as a skip
- **THEN** `result.json` has `status` `failed` and an `error` saying where the session stopped
