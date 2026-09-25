## Why

A build is made for one deployment: `freepod deploy` runs inside a project directory that
points at exactly one deployment, and releases that build into it. The data model says
otherwise. Builds are owned by a user and carry no deployment reference, so the platform
cannot answer "which builds belong to this project", and `freepod builds` run in a
project lists every build the account ever made, across all projects.

The separation was never a modelling choice. It fell out of the first deploy: there was
no deployment until a build had produced an image to create it with, so the build could
not reference one. The `custom` product has since gained a placeholder image that a
deployment serves until it is given one, which removes that constraint.

## What Changes

- **BREAKING** Every build belongs to a deployment. `build.deployment_id` is a required
  foreign key; `build.user_id` is dropped, and a build's owner is its deployment's owner.
- Existing builds are linked to the deployment that released them, first by the build
  recorded on a release and otherwise by a release whose image is the build's image.
  Builds no release ever used cannot be linked and are deleted. Their images stay in the
  registry, referenced by nothing.
- **BREAKING** Builds are created, listed and read under their deployment,
  `/users/{user_id}/deployments/{deployment_id}/builds`. The account-level
  `/users/{user_id}/builds` routes are removed with no alias; clients built against them
  must be upgraded.
- A build is refused for a deployment that is being deleted or has been.
- A release naming a build must name one of that deployment's own builds. An image may
  still be released into another deployment by submitting it without a build.
- **BREAKING** `freepod deploy` creates the deployment before building when the project
  has none, writes the pointer immediately, and builds against it. The first deploy now
  serves the placeholder until its build is released; a failed first build leaves that
  deployment in place for the next deploy to reuse. `freepod init` still writes nothing
  to the platform.
- `freepod builds` lists the current project's builds only, and requires a project that
  has deployed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `build-data-model`: a build belongs to a deployment instead of a user.
- `build-api`: builds are addressed under their deployment; creation is refused for a
  deleting or deleted deployment; the account-level routes are removed.
- `deployment-release-ledger`: a named build must belong to the deployment being
  released, not merely to its owner.
- `cli-deploy`: the deployment is created before the build on a first deploy, reversing
  the build-first ordering.
- `cli-build-submission`: a build is created against the project's deployment.
- `cli-build-history`: the history is the project's builds, not the account's.

## Impact

- **Database:** a migration adds `build.deployment_id`, backfills it, deletes unlinkable
  builds, makes the column `NOT NULL` and drops `build.user_id`. It refuses to run while
  any build is queued or running. Measured before writing this: dev holds 51 builds, of
  which 18 are unlinkable; prod holds 78, of which 16 are.
- **API:** `app/api/builds.py`, the build service, the deployment create and update
  paths (release build validation), and the build worker, which now reads the owner
  through the deployment when minting the registry capability and addressing the image
  repository.
- **CLI:** `deploy.py`, `build.py` and `history.py` in `freepod`. Installed clients stop
  working at the build step until upgraded.
- **Reverses two recorded decisions:** D1 of `add-build-subsystem` ("Builds are a
  standalone subsystem, not a sub-resource of deployments") and D6 of `add-freepod-cli`
  ("Build first, then create or update the deployment").
