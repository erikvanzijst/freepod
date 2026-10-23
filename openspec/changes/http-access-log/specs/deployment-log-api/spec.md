## ADDED Requirements

### Requirement: A read can be limited to a recent window

The endpoint SHALL accept a `lookback` window in whole seconds and, when given, SHALL return only
lines written within that window before the request. At most the requested tail SHALL be returned,
and where the window holds more, the newest lines SHALL be returned.

A window longer than the log store's retention SHALL be rejected with a reason naming the maximum,
rather than silently shortened. The window SHALL apply only to the first read: a resume point, when
supplied, SHALL take precedence.

#### Scenario: A window holding fewer lines than the tail

- **WHEN** a caller asks for the last hour and the deployment wrote 50 lines in it
- **THEN** exactly those 50 lines are returned, oldest first

#### Scenario: A window holding more lines than the tail

- **WHEN** a caller asks for the last day with a tail of 200 and the deployment wrote thousands
  of lines in it
- **THEN** the newest 200 lines from that day are returned

#### Scenario: A window beyond retention

- **WHEN** a caller asks for a window longer than the store retains
- **THEN** the request is rejected with a reason stating the longest window allowed

#### Scenario: A malformed window

- **WHEN** a caller supplies a window that is not a positive whole number of seconds
- **THEN** the request is rejected and nothing derived from it reaches the log store

#### Scenario: Reconnecting during a windowed follow

- **WHEN** a client following a windowed read reconnects with a resume point
- **THEN** the read resumes from the resume point and the window is not reapplied
