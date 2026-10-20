# client-version-gate Specification

## Purpose

Lets the backend make changes that released `freepod` CLI versions can't survive: it refuses
every request from a client older than the minimum it supports, with a message telling the
user how to upgrade, rather than letting the old client fail in ways it can't explain.

## Requirements

### Requirement: The client identifies its version on every request

The `freepod` CLI MUST send `User-Agent: freepod/<version>` (optionally followed by a
comment) on every request it makes to the platform, where `<version>` is its installed
package version.

#### Scenario: A request carries the version

- **WHEN** the client at version `0.22.0` makes any request to the platform
- **THEN** its `User-Agent` begins with `freepod/0.22.0`

### Requirement: Requests from clients below the minimum are refused

The API MUST refuse, on every endpoint and before routing, any request whose `User-Agent`
names `freepod/<version>` with a version lower than the API's minimum supported client
version. The refusal MUST be **426** with the code `client_upgrade_required` and a detail
naming the minimum version and the upgrade command for each way the CLI is commonly installed
(uv, Homebrew, pip). Versions MUST be
compared as package versions, not as text.

#### Scenario: An old client is refused everywhere

- **WHEN** the minimum is `0.22.0` and a request with `User-Agent: freepod/0.21.0` reaches
  any endpoint
- **THEN** the API responds **426** with code `client_upgrade_required` and does not run the
  endpoint

#### Scenario: The refusal says how to upgrade

- **WHEN** an old client is refused
- **THEN** the detail names the minimum version, `uv tool update freepod`,
  `brew upgrade freepod` and `pip install --upgrade freepod`

#### Scenario: A current client passes

- **WHEN** the minimum is `0.22.0` and a request carries `freepod/0.22.0` or `freepod/0.23.1`
- **THEN** the request is handled normally

#### Scenario: Versions compare numerically

- **WHEN** the minimum is `0.9.0` and a request carries `freepod/0.10.0`
- **THEN** the request is handled normally

### Requirement: Only the platform's own client is gated

Requests whose `User-Agent` does not begin with `freepod/`, or whose version can't be
parsed, MUST pass the gate unchanged.

#### Scenario: A browser is unaffected

- **WHEN** the web interface makes a request with a browser `User-Agent`
- **THEN** the gate does not refuse it

#### Scenario: An unparseable version passes

- **WHEN** a request carries `User-Agent: freepod/unknown`
- **THEN** the gate does not refuse it

### Requirement: The minimum moves with the incompatible change

The minimum supported client version MUST be a constant in the API's code, raised in the
same change as any backend change a released client can't survive. It MUST NOT be read from
configuration.

#### Scenario: The minimum is part of the change that needs it

- **WHEN** a backend change breaks a released client
- **THEN** the same change raises the minimum to the first client release that works with it
