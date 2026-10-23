# deployment-http-log-api Specification

## Purpose

The REST contract for reading a deployment's HTTP access log: which requests count as the
deployment's, what a request record contains, and how the endpoint shares the transport and
isolation rules of the pod-log endpoint on a log store that has no tenancy of its own.

## Requirements

### Requirement: A deployment's HTTP requests are readable over a streaming endpoint

The API SHALL expose `GET /api/users/{user_id}/deployments/{deployment_id}/http-log`, returning
the deployment's HTTP access log as Server-Sent Events, one request per event.

The endpoint SHALL accept `follow`, `tail`, `since` and `lookback` with the same meaning, defaults
and bounds as `deployment-log-api`, and SHALL follow that capability's keepalive, resume, timestamp
encoding, unavailability and stream-bounding rules.

#### Scenario: Reading a deployment's recent requests

- **WHEN** a caller requests the HTTP log of a deployment that has received requests
- **THEN** the response streams the most recent requests, one per event, up to the requested tail

#### Scenario: Following

- **WHEN** a caller requests follow mode
- **THEN** the response remains open and new requests are emitted as they are logged

#### Scenario: Resuming after a disconnect

- **WHEN** a caller reconnects supplying the timestamp of the last event it received
- **THEN** the stream resumes from that point with no gap

#### Scenario: A deployment that has received no requests

- **WHEN** a caller requests the HTTP log of a deployment no request has reached
- **THEN** the response is an empty stream and not an error

#### Scenario: The log store is down

- **WHEN** the log store is unreachable
- **THEN** the caller receives an error identifying a platform condition, not an empty stream

### Requirement: Requests are attributed to a deployment by its routers

The endpoint SHALL return every request routed to any of the deployment's ingress rules, across all
of its hostnames and paths, and SHALL return no request routed to any other workload.

#### Scenario: A deployment with several hostnames

- **WHEN** a deployment serves more than one hostname and each receives a request
- **THEN** every one of those requests appears in the response

#### Scenario: A deployment with several paths routed separately

- **WHEN** a deployment's chart routes some paths through a separate ingress rule
- **THEN** requests to those paths appear alongside the others

#### Scenario: Another deployment in the same namespace

- **WHEN** two deployments share a namespace and both receive requests
- **THEN** a read of one returns none of the other's requests

#### Scenario: Requests the platform handles before the tenant's router

- **WHEN** a request is answered by a platform router, such as a redirect from a legacy hostname,
  or matches no router at all
- **THEN** it does not appear in any deployment's HTTP log

### Requirement: Queries are built from authorized state only

The query issued against the log store SHALL be constructed by the API from the deployment record it
has authorized, under the same rule as `deployment-log-api`: no client-supplied string SHALL be
interpolated into it, and the only client value to reach a query SHALL be a validated number.

#### Scenario: A caller attempts to supply a selector

- **WHEN** a request carries a parameter resembling a router name or label matcher
- **THEN** it has no effect on the query the server issues

### Requirement: Each event carries an allowlisted request record

Each event SHALL carry exactly these fields: `ts`, `time`, `host`, `remote_addr`, `method`, `path`,
`protocol`, `status`, `bytes`, `duration_ms`, `referer` and `user_agent`. No other field from the
stored line SHALL be passed through, so a field later added to the stored line does not reach
tenants without a change to this contract.

#### Scenario: A complete request

- **WHEN** a request with a user agent and referer is delivered
- **THEN** its event carries all twelve fields with their recorded values

#### Scenario: Fields the platform records for itself

- **WHEN** the stored line carries the router name or any field outside the record
- **THEN** the event does not carry it

### Requirement: Record fields have fixed types and meanings

`ts` SHALL be the store's nanosecond timestamp, as a string, and is the resume point. `time` SHALL be
the request's start time in RFC 3339 UTC. `status` and `bytes` SHALL be integers. `duration_ms` SHALL
be a number in milliseconds. `referer` and `user_agent` SHALL be `null` when the request carried
none.

#### Scenario: A request without headers

- **WHEN** a request carried no `Referer` and no `User-Agent`
- **THEN** both fields are `null`, not empty strings and not `-`

#### Scenario: Two timestamps

- **WHEN** a slow request is delivered
- **THEN** `time` is when the request started and `ts` is when it was logged, after it finished

### Requirement: Lines that are not request records are skipped

A stored line that cannot be read as a request record, including access lines written before the
access log was emitted as JSON, SHALL be skipped and SHALL NOT end the stream, be delivered as raw
text, or stall the resume point.

#### Scenario: Lines from before the format change

- **WHEN** the window includes access lines in the earlier text format
- **THEN** they are omitted and the requests after them are delivered

### Requirement: HTTP log streams share the per-user stream limit

An open HTTP log stream SHALL count against the same per-user limit on concurrent streams as a pod
log stream. One limit protects the API's single worker regardless of which log a stream reads.

#### Scenario: Mixed streams at the limit

- **WHEN** a user already holds the maximum number of open streams, of either kind
- **THEN** a request for a further HTTP log stream is refused with a clear reason

### Requirement: A read cannot be pinned to a release

The endpoint SHALL NOT accept a release parameter. Ingress traffic is routed to the deployment, not
to a release, and an approximate attribution during a rollout would be wrong exactly when it is
needed.

#### Scenario: A caller asks for a release

- **WHEN** a request to the HTTP log endpoint carries a release parameter
- **THEN** the parameter has no effect on which requests are returned

### Requirement: Access is scoped to the caller's own deployments

The endpoint SHALL be authorized identically to the pod-log endpoint: callers may read their own
deployments, administrators may read any, and another user's deployment SHALL answer 404.

#### Scenario: Reading someone else's deployment

- **WHEN** a user requests the HTTP log of a deployment owned by another user
- **THEN** the response is 404, indistinguishable from a deployment that does not exist
