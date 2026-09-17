## Purpose

The GitHub identity the unattended upgrade agent acts as, the repository rules that bound
what it can do there, and the command guards that keep its normal tool use inside that
bound. The agent reads untrusted upstream content and runs shell commands, so its reach on
GitHub is bounded by its identity's permissions and by the repository's own rules. The
guards are not part of that bound: an agent can go around them.

## Requirements

### Requirement: The agent acts as a GitHub App installed on one repository
The service MUST act on GitHub only as a GitHub App registered under the owner's account
and installed on `erikvanzijst/freepod` alone. The App MUST have exactly these repository
permissions: Contents read and write, Pull requests read and write, and Metadata read. It
MUST have no other repository permission, including Workflows, Issues, Actions and
Administration, and no account permission.

The service MUST authenticate with installation access tokens that it mints from the
App's private key, each limited to `erikvanzijst/freepod`. The private key MUST NOT be
placed in an agent session's environment or in any file the service writes. Commits the
agent makes MUST be authored as the App's bot user.

The owner's own credentials MUST NOT be given to the service.

#### Scenario: A real pull request
- **WHEN** a real run opens a pull request
- **THEN** the App's bot user (`<app-slug>[bot]`) is shown as the pull request's author and as the author of its commits

#### Scenario: A workflow change is pushed
- **WHEN** the agent pushes a branch that creates or modifies a file under `.github/workflows/`
- **THEN** GitHub refuses the push, because the App lacks the Workflows permission

#### Scenario: Another repository
- **WHEN** a write to any repository other than `erikvanzijst/freepod` is attempted with a token the service minted
- **THEN** GitHub refuses it

#### Scenario: A session outlives a token
- **WHEN** a product session runs for more than an hour and then pushes a branch or opens a pull request
- **THEN** the push or pull request succeeds with a token that has not expired

### Requirement: Rulesets confine the App's writes
Two rulesets MUST exist on the repository, each with a bypass list holding the Repository
admin role in "Always allow" mode and nothing else:

- a branch ruleset that targets every branch except `refs/heads/upgrade/**`, with the
  rules "Restrict creations", "Restrict updates" and "Restrict deletions";
- a tag ruleset that targets every tag, with the rules "Restrict creations", "Restrict
  updates" and "Restrict deletions".

As a result, the App cannot push to `master`, merge a pull request into it, create,
update or delete any branch outside `upgrade/`, or create, move or delete any tag. The
owner's own pushes, merges and tags keep working, including direct pushes to `master`.

#### Scenario: The App pushes to master
- **WHEN** a push to `master` is made with a token the service minted
- **THEN** GitHub refuses it

#### Scenario: The App merges a pull request
- **WHEN** a merge of a pull request into `master` is attempted with a token the service minted
- **THEN** GitHub refuses it

#### Scenario: The App pushes another branch with the hook skipped
- **WHEN** a push of `nextcloud-34.0.4` is made with `--no-verify` and a token the service minted
- **THEN** GitHub refuses it

#### Scenario: The App creates a tag
- **WHEN** a tag is pushed, or created through the API, with a token the service minted
- **THEN** GitHub refuses it

#### Scenario: The owner pushes and merges
- **WHEN** the owner pushes a commit to `master`, or merges a pull request the App opened
- **THEN** the push or merge succeeds

### Requirement: The gh guard keeps the agent's gh use to reading and opening
The `gh` that an agent session finds first on its `PATH` MUST be a guard in front of the
real binary. The guard supplies the current installation token to the real binary, and
allows:

- read-only commands;
- `pr create` and `label create`;
- `auth status` and `auth setup-git`.

It refuses everything else, including:

- merging, closing, reopening, editing, commenting on or reviewing any pull request or
  issue;
- `auth token` and every other `auth` subcommand;
- any `repo` subcommand that writes;
- any `gh api` request whose method is not GET, or that sends fields without explicitly
  using GET.

A refused command MUST exit with a non-zero status and a message saying the guard refused
it.

The guard is not a limit on the App's access. An agent that runs the real binary, or
calls the API another way, goes around it; the App's permissions and the rulesets are the
limit.

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

### Requirement: The agent's clone pushes only upgrade branches
A `git push` from the agent's clone MUST be refused before it contacts GitHub unless every
ref it would update is under `refs/heads/upgrade/`. The branch ruleset enforces the same
rule on GitHub's side; this check gives the agent an immediate, explained refusal.

#### Scenario: An upgrade branch
- **WHEN** a real-run session pushes `upgrade/immich-v3.2.1`
- **THEN** the push proceeds

#### Scenario: Any other branch
- **WHEN** a session pushes to `master`, or to `nextcloud-34.0.4`
- **THEN** the push is refused before it contacts GitHub

### Requirement: History searches name their paths
The `git` that an agent session finds first on its `PATH` MUST be a guard in front of the
real binary. The guard refuses `git grep`, and `git log` with `-p`, `--patch`, `-S`, `-G`
or any `--pickaxe` option, unless a pathspec follows `--`. It passes every other command
to git unchanged.

A refused command MUST exit with a non-zero status and a message telling the agent to
limit the command with `-- <path>`.

#### Scenario: A grep across a whole revision
- **WHEN** the agent runs `git grep -c foo v3.2.1`
- **THEN** the command is refused, and nothing is fetched

#### Scenario: A pickaxe search without paths
- **WHEN** the agent runs `git log -S 'x' a..b`
- **THEN** the command is refused

#### Scenario: A patch log without paths
- **WHEN** the agent runs `git log -p a..b`
- **THEN** the command is refused

#### Scenario: A path-limited search
- **WHEN** the agent runs `git log -S 'x' a..b -- docker/` or `git -C repo grep foo -- src/`
- **THEN** the command runs as git would run it

#### Scenario: Other commands
- **WHEN** the agent runs `git log --oneline a..b` or `git diff a b`
- **THEN** the command runs as git would run it

### Requirement: A dry run's tokens cannot write
In dry-run mode, the service MUST mint the installation tokens a session uses with read
access only: Contents read, Pull requests read and Metadata read. The `gh` guard MUST
also refuse `pr create` and `label create`, and every push from the agent's clone MUST be
refused before it contacts GitHub.

The private key stays within the agent's reach (see design D8), so an agent that set out
to mint a writing token could still do so. A dry run guarantees that the credentials it
hands the agent cannot write.

#### Scenario: A dry-run session tries to open a pull request
- **WHEN** a session in a dry run runs `gh pr create`
- **THEN** the command is refused, and no pull request is created

#### Scenario: A dry-run session tries to push
- **WHEN** a session in a dry run pushes `upgrade/vaultwarden-1.37.3`
- **THEN** the push is refused, and no branch is created on GitHub

#### Scenario: A dry-run token reaches GitHub directly
- **WHEN** a request that writes is sent to GitHub with a token minted for a dry-run session, without passing through a guard
- **THEN** GitHub refuses it
