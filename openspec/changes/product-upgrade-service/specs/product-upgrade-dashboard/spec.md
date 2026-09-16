## Purpose

The upgrade service's web interface: what the owner can see in the run history, what they
can start from it, and who can reach it.

## ADDED Requirements

### Requirement: Every page requires the dashboard password
Every dashboard page and action except `GET /healthz` MUST require HTTP Basic
authentication whose password equals `DASHBOARD_PASSWORD`. The username is not checked.

When `DASHBOARD_PASSWORD` is unset or empty, every request except `GET /healthz` MUST be
refused.

#### Scenario: No credentials
- **WHEN** a run page is requested without credentials
- **THEN** the response has status 401 with a Basic authentication challenge

#### Scenario: The wrong password
- **WHEN** a run page is requested with a password that is not `DASHBOARD_PASSWORD`
- **THEN** the response has status 401

#### Scenario: The password was never set
- **WHEN** `DASHBOARD_PASSWORD` is unset and any page other than `/healthz` is requested, with any credentials
- **THEN** the response has status 401

### Requirement: The run history is browsable
The dashboard MUST list runs newest first. Each entry shows the run's trigger, scope,
mode, start time, duration, state, and how many products ended in each outcome.

#### Scenario: Listing runs
- **WHEN** the owner opens the dashboard
- **THEN** the most recent run is listed first, marked as a dry run or a real run

### Requirement: A run's results show everything recorded about each product
A run's page MUST show, for each product:

- the outcome, the current and target versions, and the duration;
- the token counts;
- the skip reason, the decisions needing a human, and the error, where present;
- for an opened pull request, a link to it;
- for a dry run that would open a pull request, or would skip one, the would-be
  description and patch;
- links to the HTML transcript and the other stored files.

The links to stored files MUST be signed URLs from the object store that expire within
one hour. The file contents MUST NOT pass through the dashboard. The pull request
description MUST be shown rendered from its Markdown, sanitized so that nothing in it can
run as script.

#### Scenario: A dry-run result
- **WHEN** the owner opens a dry run in which `immich` ended as `would_open`
- **THEN** the page shows the would-be pull request's description and patch for `immich`

#### Scenario: Markup in a description
- **WHEN** a would-be pull request's description contains a `<script>` element
- **THEN** the page shows the description rendered, without the script

#### Scenario: Reading a transcript
- **WHEN** the owner follows a product's transcript link
- **THEN** the browser loads the HTML rendering directly from the object store

#### Scenario: An expired link
- **WHEN** a transcript link is followed more than one hour after the page was rendered
- **THEN** the object store refuses it, and reloading the page gives a working link

### Requirement: Runs can be started from the dashboard
The dashboard MUST offer "Run now", which requests a run of the whole catalog, and "Run
one product", which requests a run of any one product a whole-catalog run would cover:
those eligible on `master`, as `product-upgrade-runs` defines. Both follow the request
rules in `product-upgrade-runs`.

While a run is active, the buttons MUST be disabled, and a request submitted anyway MUST
be refused with a message saying why.

#### Scenario: A fresh deployment
- **WHEN** the owner opens the dashboard before any run has happened
- **THEN** "Run one product" offers every eligible product on `master`

#### Scenario: Starting a run
- **WHEN** the owner presses "Run now" while no run is active
- **THEN** the dashboard confirms the request, and the run appears in the history as active

#### Scenario: Starting a run while one is active
- **WHEN** a request is submitted while a run is active
- **THEN** the dashboard shows that a run is already in progress, and no run starts

### Requirement: Progress is shown while a run is active
While a run is active, the dashboard MUST show which product is running and for how long,
and the outcomes of the products that have finished. The display MUST refresh itself at
least every ten seconds without a page reload.

It MUST also show the running product's session as it is written: its latest steps when
the panel opens, then each new step, without a page reload. A refresh MUST read only what
the session wrote since the previous refresh, so that its cost does not grow with the
length of the transcript. Every step MUST be redacted as stored files are
(`product-upgrade-history`) and shown as plain text: nothing from the transcript is
rendered as markup.

#### Scenario: Watching a run
- **WHEN** the owner has the dashboard open while the second of three products runs
- **THEN** the page names the running product and its elapsed time, and shows the first product's outcome
- **AND** when the second product finishes, the page shows its outcome without being reloaded

#### Scenario: Opening the panel mid-session
- **WHEN** the owner opens the dashboard after a product's session has written many steps
- **THEN** the panel shows the session's latest steps, not the whole transcript

#### Scenario: A new step
- **WHEN** the running session writes a step
- **THEN** the panel adds it within ten seconds, and that refresh fetches no step already shown

#### Scenario: A secret in the live session
- **WHEN** the running session prints an installation token minted for it
- **THEN** the panel shows `[redacted:github-token]` in its place

#### Scenario: Markup in the live session
- **WHEN** a step contains `<script>alert(1)</script>`
- **THEN** the panel shows that text, and nothing runs

### Requirement: Each pull request's current state is shown
For every product result with a pull request URL, the dashboard MUST show the pull
request's current state on GitHub: open, draft, merged or closed. The state is fetched
from GitHub when a page is rendered, and a fetched state MUST NOT be reused for more than
five minutes. The dashboard MUST fetch it with an installation token that can only read.

When GitHub cannot be reached, the page MUST still render, and the state is shown as
unknown.

#### Scenario: A merged pull request
- **WHEN** a pull request the service opened has been merged, and more than five minutes have passed since its state was last fetched
- **THEN** the run's page shows it as merged

#### Scenario: GitHub is unreachable
- **WHEN** GitHub does not respond while a run's page is rendered
- **THEN** the page renders, with each pull request's state shown as unknown
