# deployment-log-api Specification

## Purpose

The REST contract for reading a deployment's application output — its transport, its resume point,
what a caller may ask for, how it behaves when the log store is unavailable, and the isolation
rules that keep one tenant's request from reaching another tenant's lines on a log store that
has no tenancy of its own.

## Requirements

### Requirement: A deployment's output is readable over a streaming endpoint

The API SHALL expose `GET /api/users/{user_id}/deployments/{deployment_id}/log`, returning the
deployment's application output as a stream of events, each carrying one log line.

The response SHALL be delivered as **Server-Sent Events**, not as a WebSocket and not as an
unframed body. The traffic is unidirectional and SSE is readable by the existing client without
adding a dependency or reimplementing the client's authentication and refresh contract, while
still providing the framing that keepalives, per-line attribution and mid-stream error signaling
all require.

Each log line SHALL be delivered as one event carrying the line, the time it was written, and the
identifier of the release that produced it where the deployment's pods are release-labeled. The
timestamp doubles as the resume point, so a client reconnecting tracks no value beyond what it
already holds.

The response SHALL be sent unbuffered, and SHALL declare itself uncacheable. A cached or buffered
copy of a live stream is a wrong copy.

The endpoint SHALL support both a bounded read, which returns what is available and completes,
and a follow mode, which holds the response open and emits lines as they arrive.

#### Scenario: Reading a running deployment's output

- **WHEN** a caller requests the log of a deployment whose pods are running
- **THEN** the response streams that deployment's output, one log line per event

#### Scenario: Following

- **WHEN** a caller requests follow mode
- **THEN** the response remains open and new lines are emitted as they are produced

#### Scenario: A deployment that has produced no output

- **WHEN** a caller requests the log of a deployment whose pods have written nothing
- **THEN** the response is an empty stream and not an error

#### Scenario: A line is attributable without a second request

- **WHEN** a line from a release-labeled pod is delivered
- **THEN** the event carries the identifier of the release that produced it

### Requirement: An open stream is kept alive through silence

The endpoint SHALL emit a periodic keepalive on an open follow-mode stream, whether or not the
application is producing output.

The keepalive interval SHALL be shorter than the shortest connection timeout in the request path,
which includes the client, the platform edge, and network equipment outside the platform's
control. It SHALL be configurable, because the tightest timeout is not a property of this
codebase: the platform edge fronts the API with a proxy whose timeouts this repository does not
hold.

A keepalive SHALL be distinguishable from output and SHALL NOT appear in, terminate, or alter the
log stream a client is assembling. It SHALL NOT be an empty log line.

A keepalive SHALL be a transport-level construct rather than an event, and SHALL NOT carry a
resume cursor. It belongs to a lower layer than the log stream and describes the connection, not
the log. Advancing a cursor from a keepalive would move the resume point past instants at which
no line had been delivered, permanently skipping any line that arrives late bearing an earlier
timestamp — which an unadvanced cursor still collects on the next resume.

An application that is merely quiet SHALL NOT cause a stream to be closed by any party.

#### Scenario: An application says nothing for a long time

- **WHEN** a follow-mode stream is open and the application produces no output for many minutes
- **THEN** the connection remains open and usable
- **AND** output resumes on the same stream when the application writes again

#### Scenario: Keepalives are not output

- **WHEN** keepalives have been emitted during a quiet period
- **THEN** the log the client assembled contains no trace of them

#### Scenario: A quiet period does not move the resume point

- **WHEN** a stream is kept alive through a long quiet period and is then interrupted
- **THEN** the client resumes from the last log line it received, not from the quiet period's end

#### Scenario: A quiet application is not reported as disconnected

- **WHEN** an application is quiet for longer than the shortest timeout in the path
- **THEN** the client is not told the stream failed

### Requirement: A read follows the deployment by default and can be pinned to any release

The endpoint SHALL, by default, return the output of the deployment as a whole, continuing
across redeploys and container restarts, so that a caller following a running application
observes a rollover rather than the stream ending.

A caller SHALL be able to pin the read to a single release by its per-deployment number, in
which case only that release's output is returned.

Pinning SHALL work for a release whose pods no longer exist, including one that failed and was
rolled back. This is the case the endpoint exists to serve and SHALL NOT be treated as an
exceptional path.

Pinning SHALL be offered for every deployment, whatever its product. The endpoint SHALL NOT vary
its answer by chart.

A release that was applied before its product's chart rendered release labels has no labeled
output. A pinned read of such a release SHALL return an empty stream. This SHALL be the only
case in which a release that ran answers a pinned read with nothing, and it SHALL disappear
once the log store's retention has removed that release's output.

#### Scenario: A rollout happens while following

- **WHEN** a caller is following a deployment and a new release becomes live
- **THEN** the stream continues, carrying the new release's output

#### Scenario: Pinning to a failed release

- **WHEN** a caller requests the log of a release that failed and whose pods were deleted
- **THEN** that release's output is returned

#### Scenario: Pinning to a release of another deployment

- **WHEN** a caller names a release number that does not belong to the addressed deployment
- **THEN** the request is refused and no output from any other deployment is returned

#### Scenario: Pinning on a curated product

- **WHEN** a caller pins a read to a release of a deployment of any curated product
- **THEN** that release's output is returned
- **AND** the request is not refused as unsupported by the product

#### Scenario: Pinning to a release that never produced a pod

- **WHEN** a caller pins to a release that has not been applied, or that failed before any pod
  started
- **THEN** the caller is told that release produced no output because it never ran
- **AND** does not receive a silent empty stream indistinguishable from an application that
  printed nothing

### Requirement: Every line carries the time it was written

Each log event SHALL carry the timestamp the log store recorded for that line, at nanosecond
resolution.

The timestamp SHALL be carried whether or not the application timestamps its own output, because
many do not and the store holds the only record of when such a line was written. A client SHALL
be able to present it; the endpoint SHALL NOT decide that for the client.

The timestamp SHALL be transmitted as a **string**, and SHALL NOT be transmitted as a JSON
number. A nanosecond timestamp exceeds the range an IEEE-754 double represents exactly, so a
numeric encoding would be silently rounded by conforming consumers, corrupting both the
displayed time and the resume point without raising an error.

#### Scenario: An application that does not timestamp its own output

- **WHEN** a line is delivered from an application that writes no timestamps
- **THEN** the event still carries the time the line was written

#### Scenario: Precision survives the wire

- **WHEN** an event's timestamp is read back by a consumer using IEEE-754 double arithmetic for
  numbers
- **THEN** the full nanosecond value is preserved exactly

### Requirement: Reads start at the present and resume from the timestamp

The endpoint SHALL start from the recent end of the log by default, returning a bounded number
of trailing lines rather than everything the deployment has ever written. A long-running
application's full history SHALL NOT be spooled to a client that asked to watch what is
happening now.

The timestamp each event already carries SHALL be the resume point, and the endpoint SHALL accept
it to continue a read from where the client last reached. There SHALL NOT be a separate cursor
token: two representations of one fact can drift apart, and the client parses the timestamp
regardless in order to present it.

Resumption SHALL be **inclusive** of the supplied timestamp: the read continues from that
instant, not from the instant after it. Every line not yet delivered is at or after it, so an
inclusive resume cannot leave a gap, and resuming one nanosecond later would silently discard any
other line sharing that instant.

Resumption SHALL therefore be **at least once**. A line sharing that instant may be delivered a
second time; that is the mechanism working, not a defect. A duplicated line after a reconnect is
acceptable and a missing one is not, and this SHALL NOT be traded the other way.

The resume point SHALL NOT be a byte offset. Byte offsets suit the build log, which accumulates
into a single stored artifact; a deployment's log has no such artifact and no meaningful origin
to count from.

A timestamp supplied by a client is the only client-supplied value that reaches the log store's
query. That the client legitimately holds this value SHALL NOT make it trusted: it SHALL be
parsed and validated before use and rejected if it is not a timestamp, and SHALL NOT be forwarded
to the store as an unvalidated string. This is the single exception to the rule that queries
carry nothing from the client, and only because the value becomes a number first.

#### Scenario: First read of a long-running application

- **WHEN** a caller opens the log of an application that has been running for weeks
- **THEN** a bounded number of recent lines is returned rather than the entire history

#### Scenario: Every event can be resumed from

- **WHEN** any event is delivered
- **THEN** its timestamp is sufficient to resume the read from that point

#### Scenario: Resuming after a disconnect

- **WHEN** a caller reconnects supplying the timestamp from the last event it received
- **THEN** the stream resumes from that point with no gap

#### Scenario: Lines sharing a timestamp at the resume boundary

- **WHEN** a caller resumes at a point where several lines share one timestamp
- **THEN** no line produced at or after that instant is omitted
- **AND** a line may be delivered a second time rather than being lost

#### Scenario: A malformed resume point

- **WHEN** a caller supplies a resume value that is not a valid timestamp
- **THEN** the request is rejected
- **AND** nothing derived from the supplied value reaches the log store

### Requirement: Queries are constructed by the server from authorized state

The query issued against the log store SHALL be constructed by the API from the deployment
record it has already authorized, and no client-supplied string SHALL be interpolated into it.

The API SHALL NOT accept a query expression, a selector, a label matcher or a namespace from the
client under any parameter name.

This constraint is load-bearing rather than defensive: the log store holds every tenant's output
and the platform's own in a single tenancy, so a client-influenced selector would be both a
cross-tenant read and a platform-internal read.

#### Scenario: A caller attempts to supply a selector

- **WHEN** a request carries a parameter that looks like a query expression or label matcher
- **THEN** it has no effect on the query the server issues

#### Scenario: Only the addressed deployment's lines are returned

- **WHEN** any request to the endpoint succeeds
- **THEN** the response contains lines from the addressed deployment's pods and from no other
  workload

### Requirement: The stream carries the application's output, not the platform's

The query SHALL exclude the platform's SSH sidecar container, whose output belongs to the
platform rather than to the tenant's application.

#### Scenario: An idle deployment whose sidecar is being probed

- **WHEN** a caller reads the log of a deployment whose SSH sidecar is receiving liveness probes
- **THEN** no line written by the sidecar appears in the response

#### Scenario: A product running several application containers

- **WHEN** a caller reads the log of a deployment whose pods run more than one non-sidecar
  container
- **THEN** every one of those containers' output appears in the response

### Requirement: Access is scoped to the caller's own deployments

The endpoint SHALL be authorized identically to the other user-scoped deployment routes:
callers may read their own deployments, and administrators may read any.

A deployment belonging to another user SHALL answer 404, identically to one that does not
exist, so the endpoint cannot be used to discover other users' deployments.

#### Scenario: Reading one's own deployment

- **WHEN** a user requests the log of a deployment they own
- **THEN** the request succeeds

#### Scenario: Reading someone else's deployment

- **WHEN** a user requests the log of a deployment owned by another user
- **THEN** the response is 404, indistinguishable from a deployment that does not exist

### Requirement: Log store unavailability is reported as a platform condition

When the log store cannot be reached or fails a query, the endpoint SHALL report a platform
error distinguishable from a successful read that found nothing.

An unavailable store SHALL NOT produce an empty successful response. An empty success asserts
that the application produced no output, which is a different and misleading claim, and is the
one failure mode this requirement exists to prevent.

#### Scenario: The log store is down

- **WHEN** the log store is unreachable and a caller requests a deployment's log
- **THEN** the caller receives an error identifying this as a platform condition
- **AND** does not receive an empty successful stream

#### Scenario: The store fails mid-stream

- **WHEN** a follow-mode stream is interrupted by a store failure after lines have been sent
- **THEN** the caller can distinguish the interruption from the end of the output

### Requirement: Streams are bounded so one tenant cannot exhaust the API

The endpoint SHALL be served without blocking a worker thread for the life of the connection,
and SHALL NOT hold a database session open across the stream. Authorization resolves the
deployment, the session is released, and only then does streaming begin.

The API SHALL bound the number of concurrent streams a single user may hold open, and SHALL
close a stream that has been idle beyond a configured period.

These limits exist because the API runs as a single worker process whose remaining endpoints are
served from a bounded thread pool; an unbounded number of long-lived streams would deny service
to every other endpoint, not merely to this one.

#### Scenario: A user opens many streams

- **WHEN** a user attempts to hold more concurrent streams open than the configured limit
- **THEN** the excess requests are refused with a clear reason
- **AND** other endpoints continue to be served

#### Scenario: An idle stream

- **WHEN** a follow-mode stream produces no output for longer than the configured idle period
- **THEN** the stream is closed

#### Scenario: An application logging continuously

- **WHEN** a tenant application writes output continuously at a high rate while a stream is open
- **THEN** other API endpoints continue to be served
