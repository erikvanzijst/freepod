## Purpose

What the upgrade service records about every run and every product, where it keeps it,
for how long, and the rule that nothing it stores contains a secret value.

## Requirements

### Requirement: Every run and product result is indexed in the database
For every run, the service MUST record in the deployment's database:

- its trigger (scheduled or manual);
- its scope (the whole catalog, or the product requested);
- its mode (dry or real);
- its start and finish times, and its state (`running`, `completed`, `canceled` or
  `interrupted`);
- the pi version, the model id and the thinking level it ran with.

For every product in a run, the service MUST record:

- the slug and the outcome;
- the current and target versions;
- the pull request URL and whether it is a draft;
- the branch, the skip reason, the decisions needing a human, and the error;
- the start and finish times;
- the input and output token totals, and the peak context, taken from the agent session;
- the commit of `master` its clone was taken at, which is the commit its skill came from.

#### Scenario: After a product completes
- **WHEN** a product's session ends with a valid result
- **THEN** its row carries the outcome and versions from `result.json`, its timings, its token counts, and the commit its skill came from

#### Scenario: Provenance of a run
- **WHEN** a run is inspected after the skill has changed on `master`
- **THEN** each of its product results names the commit whose skill it followed

### Requirement: Each product's files are kept in the bucket
For every product whose session started, the service MUST store these files in the
deployment's bucket, under a key prefix unique to that run and product:

- the session transcript as written by the agent harness;
- the harness's HTML rendering of that transcript;
- the session's standard output;
- `result.json`, when one was written;
- `body.md` and `change.patch`, when the session produced them.

The files MUST be stored when the product ends, whatever the outcome, including
`timed_out`, `canceled` and `failed`.

#### Scenario: A dry run that would open a pull request
- **WHEN** a product ends as `would_open`
- **THEN** its transcript, the HTML rendering, its output, `result.json`, `body.md` and `change.patch` are in the bucket

#### Scenario: A session that timed out
- **WHEN** a product ends as `timed_out`
- **THEN** its transcript up to the moment it was terminated, and its HTML rendering, are in the bucket

#### Scenario: An interrupted product
- **WHEN** a product is marked `interrupted` after a restart
- **THEN** its result is shown without stored files

### Requirement: History is kept indefinitely
The service MUST NOT delete or expire any run, product result or stored file.

#### Scenario: An old run
- **WHEN** a run from more than a year ago is opened in the dashboard
- **THEN** its results and stored files are available

### Requirement: No secret value is stored
Before a file is uploaded, and before any value that came from a session is written to
the database, the service MUST replace every occurrence of these values with a marker
naming the secret:

- every installation token the service minted during the run, as
  `[redacted:github-token]`;
- the value of `GITHUB_APP_PRIVATE_KEY`, the key it decodes to, and each line of that
  key's body, as `[redacted:GITHUB_APP_PRIVATE_KEY]`;
- the current values of `INFERENCE_API_KEY` and `DASHBOARD_PASSWORD`, as
  `[redacted:INFERENCE_API_KEY]` and `[redacted:DASHBOARD_PASSWORD]`.

An unset or empty secret MUST NOT cause any replacement.

The HTML rendering MUST be produced from the already-redacted transcript.

#### Scenario: The agent prints a token
- **WHEN** a session's output and transcript contain an installation token the service minted for it
- **THEN** the stored output, transcript and HTML rendering contain `[redacted:github-token]` in its place, and never the token

#### Scenario: The agent prints part of the private key
- **WHEN** a transcript contains one line of the App's decoded private key
- **THEN** the stored transcript contains `[redacted:GITHUB_APP_PRIVATE_KEY]` in its place

#### Scenario: A secret in a result field
- **WHEN** a `result.json` `error` contains the value of `INFERENCE_API_KEY`
- **THEN** the error stored in the database and the stored `result.json` contain the marker instead

#### Scenario: An unset secret
- **WHEN** `DASHBOARD_PASSWORD` is unset
- **THEN** the stored files are identical to what the session wrote, apart from the replacements for the other secrets
