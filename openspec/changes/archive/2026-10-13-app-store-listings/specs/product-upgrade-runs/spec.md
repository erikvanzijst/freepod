## MODIFIED Requirements

### Requirement: A real run's proposal is published by the service
When a real run's session ends with an accepted result whose `status` is `would_open`, the
service MUST publish the proposal itself:

1. Apply the session's `change.patch` to the service's own clone, on top of
   `master` as it is when the service checks the proposal.
2. Push the result as `upgrade/<slug>-<target_version>`, without force.
3. Create the `product-upgrade` label if it is missing.
4. Open a pull request against `master` with that label, the title from `meta.json`,
   `body.md` as its description, and as a draft when `draft` is true.

The product's recorded outcome is then `opened`, with the pull request's URL and branch.

Before publishing, the service MUST check the proposal. It MUST refuse it when:

- `meta.json`, `body.md` or `change.patch` is missing;
- the patch is empty or does not apply;
- the patch touches any path other than files under the product's catalog folder,
  `products/catalog/<slug>/`, and files under `products/<slug>/`;
- the patch creates a symbolic link or a submodule entry;
- `target_version` does not form a valid branch name;
- the title is not one line of the form `<Product>: Upgrade to <target_version>`;
- `body.md` is longer than GitHub accepts;
- `body.md` contains a link to an issue or pull request on GitHub, or an @-mention.

Those checks are part of judging the result. A refusal is handled like any other rejected
result: it gets the one repair turn, and the product is recorded as `failed` if the
corrected proposal is still refused. The refusal's reason is what the repair turn is
given.

The title and description MUST be redacted like every stored file before they are sent,
so that no secret the session could see reaches the public pull request.

If GitHub refuses the push or the pull request, or cannot be reached, the product MUST
be recorded as `failed` with GitHub's reason. A branch that already exists counts as such
a refusal. Nothing is retried.

In a dry run, nothing is published, and the outcome stays `would_open`. The proposal is
still checked, so that a dry run catches what a real run would refuse.

#### Scenario: A real run publishes
- **WHEN** a real run's session for `immich` ends with `would_open`, target `v2.2.0`, `draft` true, and a patch that changes `products/catalog/immich/immich.yaml` and `products/catalog/immich/releases.yaml`
- **THEN** the service pushes `upgrade/immich-v2.2.0` and opens a draft pull request labeled `product-upgrade`
- **AND** the product is recorded as `opened`, with that pull request's URL

#### Scenario: A patch touches another product
- **WHEN** a session for `immich` proposes a patch that also changes `products/catalog/nextcloud/nextcloud.yaml`
- **THEN** nothing is pushed
- **AND** the session gets its repair turn, told that the patch touches a path outside `immich`'s

#### Scenario: A patch touches the shared catalog schema
- **WHEN** a session for `immich` proposes a patch that changes `products/catalog/catalog.schema.json`
- **THEN** nothing is pushed
- **AND** the session gets its repair turn, told that the patch touches a path outside `immich`'s

#### Scenario: A patch touches the workflows
- **WHEN** a session proposes a patch that changes `.github/workflows/ci.yml`
- **THEN** nothing is pushed, and the proposal is refused before contacting GitHub

#### Scenario: A description links an upstream issue
- **WHEN** a session's `body.md` contains `https://github.com/immich-app/immich/issues/123`
- **THEN** nothing is pushed, and the session gets its repair turn

#### Scenario: The branch already exists
- **WHEN** a real run publishes `upgrade/immich-v2.2.0` while that branch exists on GitHub
- **THEN** the product is recorded as `failed`, naming the existing branch

#### Scenario: A dry run checks without publishing
- **WHEN** a dry run's session proposes a patch that touches another product's files
- **THEN** the session gets its repair turn
- **AND** nothing is pushed, whatever the outcome
