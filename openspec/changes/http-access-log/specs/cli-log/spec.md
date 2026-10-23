## ADDED Requirements

### Requirement: The HTTP access log is available behind a flag

`freepod log --http` SHALL stream the project's deployment's HTTP access log instead of its
application output, using the same deployment resolution, stdout/stderr split, follow, reconnect,
keepalive and silence-versus-failure behavior as the pod log.

#### Scenario: Reading the access log

- **WHEN** `freepod log --http` runs in a project directory whose deployment has received requests
- **THEN** the most recent requests are printed to stdout, one per line

#### Scenario: Following the access log

- **WHEN** `freepod log --http -f` runs and a request reaches the deployment
- **THEN** the request is printed as it is logged, and the stream stays open

#### Scenario: No requests

- **WHEN** the deployment has received no requests
- **THEN** the client says so on stderr and exits successfully

### Requirement: Access log lines are in Combined Log Format

Without `--json`, each request SHALL print as one line in Combined Log Format: client address,
`-`, `-`, the request's start time in brackets in UTC, the quoted request line, status, response
size, and the quoted referer and user agent. An absent referer or user agent SHALL print as `"-"`.

Characters that would break the format inside a quoted field SHALL be escaped, so that each request
stays exactly one parseable line.

#### Scenario: A typical request

- **WHEN** a `GET /index.html` over HTTP/2.0 from `203.0.113.7` returned 200 with 512 bytes
- **THEN** the line reads `203.0.113.7 - - [23/Oct/2026:12:50:48 +0000] "GET /index.html HTTP/2.0" 200 512 "<referer>" "<user agent>"`

#### Scenario: A path containing a quote

- **WHEN** a request path contains a double quote
- **THEN** the quote is escaped and the line still parses as Combined Log Format

#### Scenario: Timestamps requested

- **WHEN** `freepod log --http -t` runs
- **THEN** each line is prefixed with the time the platform logged the request, before the
  Combined Log Format fields

### Requirement: JSON output is one object per line

`--json` SHALL print each event's record as one compact JSON object per line, with no enclosing
array, for both log types. For the pod log the object SHALL carry `ts`, `line` and `release`. For
the access log it SHALL carry the request record the platform delivers. `-t` SHALL NOT alter JSON
output, since `ts` is already present.

#### Scenario: Piping pod output to a JSON processor

- **WHEN** `freepod log --json` is piped to a JSON-lines consumer
- **THEN** every stdout line parses on its own as an object with `ts`, `line` and `release`

#### Scenario: Access log as JSON

- **WHEN** `freepod log --http --json` runs
- **THEN** every stdout line is one request record, including `host` and `duration_ms`

#### Scenario: Timestamp precision survives

- **WHEN** a JSON line is printed
- **THEN** `ts` is a string carrying the full nanosecond value

### Requirement: A read can be limited to a recent window

`--since <duration>` SHALL limit the read to the given window before now, for both log types. A
duration SHALL be a positive whole number followed by `s`, `m`, `h` or `d`. At most `-n` lines SHALL
be printed, the newest in the window.

A malformed duration SHALL be refused before any request is made. A window the platform refuses as
longer than its retention SHALL be reported with the platform's reason.

#### Scenario: Looking back an hour

- **WHEN** `freepod log --since 1h` runs
- **THEN** only lines written in the last hour are printed, at most the tail's worth

#### Scenario: A malformed duration

- **WHEN** `freepod log --since 1w` or `--since 90` runs
- **THEN** the client reports the accepted forms and exits non-zero without contacting the platform

#### Scenario: Beyond retention

- **WHEN** `freepod log --since 30d` runs
- **THEN** the client reports the platform's limit and exits non-zero

#### Scenario: Following after a window

- **WHEN** `freepod log --since 10m -f` runs
- **THEN** the last ten minutes are printed, and the stream then follows new lines

### Requirement: The access log cannot be pinned to a release

`--http` together with `-r` SHALL be refused as a usage error before any request is made, because
ingress traffic is not attributable to a release.

#### Scenario: Pinning the access log

- **WHEN** `freepod log --http -r 3` runs
- **THEN** the client reports that the access log cannot be pinned to a release and exits non-zero
