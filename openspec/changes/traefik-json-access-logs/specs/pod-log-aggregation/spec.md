## MODIFIED Requirements

### Requirement: Parsed Traefik access logs

The system SHALL emit Traefik access logs as one JSON object per request and SHALL parse them so
ingress requests are queryable by structured fields rather than raw text.

Each access-log stream SHALL carry `method`, `status` and `router` labels, taken from the request
method, the status returned to the client, and the name of the router that matched. These labels
SHALL be treated as a contract: the tenant-facing access log selects a deployment's requests by
`router`.

#### Scenario: Ingress request is queryable by status and route

- **WHEN** Traefik emits an access-log line for an incoming request
- **THEN** the line is stored with `method`, `status` and `router` labels, making the request
  filterable in Grafana without full-text search

#### Scenario: Every field is readable from the line itself

- **WHEN** an access-log line is read from the store
- **THEN** the request's start time, client address, host, method, path, protocol, status,
  response size, duration, referer and user agent can be read from the line by parsing it as JSON

#### Scenario: A request that matched no router

- **WHEN** Traefik logs a request that no router matched
- **THEN** the line is collected without a `router` label and is selected by no router match

#### Scenario: Traefik's own log lines

- **WHEN** Traefik writes a line that is not an access-log entry
- **THEN** the line is collected without `method`, `status` or `router` labels and without error

## ADDED Requirements

### Requirement: Access logs record only allowlisted fields

The access log SHALL record only the fields a request record needs: start time, client address,
host, method, path, protocol, downstream status, response size, duration and router name. Other
fields Traefik can emit SHALL be dropped before they are written.

Request headers SHALL be dropped by default. Only `User-Agent` and `Referer` SHALL be recorded.
Credentials such as `Cookie` and `Authorization` SHALL never reach the log store.

#### Scenario: A request carrying credentials

- **WHEN** a request with `Cookie` and `Authorization` headers is logged
- **THEN** neither header's value appears in the stored line

#### Scenario: Browser identification is kept

- **WHEN** a request with `User-Agent` and `Referer` headers is logged
- **THEN** both values appear in the stored line

#### Scenario: A field outside the allowlist

- **WHEN** Traefik would emit a field outside the allowlist, such as the upstream service address
- **THEN** the field does not appear in the stored line
