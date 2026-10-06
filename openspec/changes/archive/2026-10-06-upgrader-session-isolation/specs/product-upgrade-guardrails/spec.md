## ADDED Requirements

### Requirement: Sessions run as a user that can read none of the service's secrets
Every agent session, and every process it starts, MUST run as a dedicated unprivileged
user. That user MUST NOT be the user the service runs as, and MUST NOT be able to:

- read the environment of any of the service's processes, or of the container's init
  process;
- read any file the service writes for itself, including its installation tokens other
  than the session's own, and its system git configuration as anything but read-only;
- signal, trace or otherwise act on the service's processes;
- gain any other user's privileges, through `sudo` or otherwise.

The service's secrets are `GITHUB_APP_PRIVATE_KEY`, `DATABASE_URL`, the `PG` and `AWS_`
variables, and `SMTP_PASS`. None of them MUST be present in a session's environment.
`INFERENCE_API_KEY` and the session's own read-only installation token are the only
credentials a session holds.

#### Scenario: Reading the service's environment
- **WHEN** a session runs `cat /proc/<pid>/environ` for the service's process or the container's init process
- **THEN** the read is refused, and no secret is printed

#### Scenario: Signaling the service
- **WHEN** a session sends a signal to the service's process
- **THEN** the signal is refused, and the service keeps running

#### Scenario: Escalating
- **WHEN** a session runs `sudo -n true` or `sudo -u node true`
- **THEN** the command is refused

### Requirement: Sessions push nothing and open nothing
No agent session MUST write to GitHub, in a dry run or a real run. A `git push` from a
session's clone MUST be refused before it contacts GitHub, and the `gh` guard MUST refuse
`pr create` and `label create`. The service alone pushes branches and opens pull requests
(`product-upgrade-runs`).

#### Scenario: A real-run session tries to push
- **WHEN** a session in a real run pushes `upgrade/vaultwarden-1.37.3`
- **THEN** the push is refused, and no branch is created on GitHub

#### Scenario: A session tries to open a pull request
- **WHEN** a session in any mode runs `gh pr create`
- **THEN** the command is refused, and no pull request is created

## MODIFIED Requirements

### Requirement: The agent acts as a GitHub App installed on one repository
The service MUST act on GitHub only as a GitHub App registered under the owner's account
and installed on `erikvanzijst/freepod` alone. The App MUST have exactly these repository
permissions: Contents read and write, Pull requests read and write, and Metadata read. It
MUST have no other repository permission, including Workflows, Issues, Actions and
Administration, and no account permission.

The service MUST authenticate with installation access tokens that it mints from the
App's private key, each limited to `erikvanzijst/freepod`. The private key MUST NOT be
readable by an agent session in any way: not in its environment, not in any file, and
not through any process the session can inspect. Commits on the branches the service
pushes MUST be authored and committed as the App's bot user.

The owner's own credentials MUST NOT be given to the service.

#### Scenario: A real pull request
- **WHEN** a real run opens a pull request
- **THEN** the App's bot user (`<app-slug>[bot]`) is shown as the pull request's author and as the author of its commits

#### Scenario: A patch claims another author
- **WHEN** a session's `change.patch` names the owner as the author of its commits
- **THEN** the commits the service pushes are authored by the App's bot user

#### Scenario: A workflow change is pushed
- **WHEN** a push of a branch that creates or modifies a file under `.github/workflows/` is made with a token the service minted
- **THEN** GitHub refuses the push, because the App lacks the Workflows permission

#### Scenario: Another repository
- **WHEN** a write to any repository other than `erikvanzijst/freepod` is attempted with a token the service minted
- **THEN** GitHub refuses it

#### Scenario: A session outlives a token
- **WHEN** a product session runs for more than an hour and then reads from GitHub
- **THEN** the read succeeds with a token that has not expired

### Requirement: The gh guard keeps the agent's gh use to reading and opening
The `gh` that an agent session finds first on its `PATH` MUST be a guard in front of the
real binary. The guard supplies the current installation token to the real binary, and
allows:

- read-only commands;
- `auth status` and `auth setup-git`.

It refuses everything else, including:

- `pr create` and `label create`;
- merging, closing, reopening, editing, commenting on or reviewing any pull request or
  issue;
- `auth token` and every other `auth` subcommand;
- any `repo` subcommand that writes;
- any `gh api` request whose method is not GET, or that sends fields without explicitly
  using GET.

A refused command MUST exit with a non-zero status and a message saying the guard refused
it.

The guard is not a limit on the session's access. A session that runs the real binary, or
calls the API another way, goes around it. The limit is that the session holds only a
read-only token.

#### Scenario: A merge
- **WHEN** the agent runs `gh pr merge 123`
- **THEN** the command is refused, and nothing is sent to GitHub

#### Scenario: A write through the API
- **WHEN** the agent runs `gh api -X POST repos/erikvanzijst/freepod/issues/1/comments`
- **THEN** the command is refused

#### Scenario: Fields imply a write
- **WHEN** the agent runs `gh api repos/erikvanzijst/freepod/labels -f name=x`
- **THEN** the command is refused

#### Scenario: Reading the token
- **WHEN** the agent runs `gh auth token`
- **THEN** the command is refused, and the token is not printed

#### Scenario: Reading is allowed
- **WHEN** the agent runs `gh pr list --state open` or `gh api --paginate repos/immich-app/immich/releases`
- **THEN** the command runs and returns GitHub's answer

### Requirement: A dry run's tokens cannot write
The service MUST mint every installation token a session can reach with read access
only: Contents read, Pull requests read and Metadata read, in a dry run and a real run
alike. In a real run, the service MUST mint the token that writes only when it publishes
a proposal. It MUST hold that token only in its own process memory and in the child
processes that push and open the pull request. Those children MUST run as the service's
user, never as the session's.

A dry run never mints a token that writes.

#### Scenario: A dry-run session tries to open a pull request
- **WHEN** a session in a dry run runs `gh pr create`
- **THEN** the command is refused, and no pull request is created

#### Scenario: A dry-run session tries to push
- **WHEN** a session in a dry run pushes `upgrade/vaultwarden-1.37.3`
- **THEN** the push is refused, and no branch is created on GitHub

#### Scenario: A dry-run token reaches GitHub directly
- **WHEN** a request that writes is sent to GitHub with a token minted for a session, in a dry run or a real run, without passing through a guard
- **THEN** GitHub refuses it

#### Scenario: A dry run mints only reading tokens
- **WHEN** a dry run executes any number of products
- **THEN** every installation token the service minted for that run carries read permissions only

## REMOVED Requirements

### Requirement: The agent's clone pushes only upgrade branches
**Reason**: Sessions no longer push at all (see "Sessions push nothing and open nothing").
The branch ruleset still confines the App's own pushes to `upgrade/**`.
**Migration**: None. The service pushes `upgrade/<slug>-<target>` itself, after validating
the session's proposal.
