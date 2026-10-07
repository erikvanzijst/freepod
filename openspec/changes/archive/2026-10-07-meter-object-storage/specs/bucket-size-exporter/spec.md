## Purpose

Garage publishes no per-bucket metrics. This capability reads every deployment bucket's
size from an environment's Garage instance and publishes it to Prometheus, at a bounded
load on Garage that does not grow with the number of buckets, keeping recently written
buckets fresher than idle ones.

## ADDED Requirements

### Requirement: Each environment's buckets are read by its own exporter

Each environment SHALL run one bucket size exporter beside its own Garage instance. It
SHALL read that instance only.

The exporter SHALL consider exactly the buckets carrying a global alias of the form
`dep-<deployment id>`. Other buckets, including the platform's own, SHALL NOT be read or
published. The bucket list SHALL be refreshed periodically from Garage, so a bucket is
picked up after it is created and dropped after it is deleted, with no restart.

#### Scenario: A new deployment's bucket is picked up

- **WHEN** a deployment's bucket is created while the exporter is running
- **THEN** it is read and published after the next bucket list refresh

#### Scenario: The platform bucket is ignored

- **WHEN** the instance holds the platform's `artifacts` bucket
- **THEN** the exporter neither reads nor publishes it

### Requirement: Garage load is bounded by a configured rate

The exporter SHALL read bucket sizes one bucket per call, at no more than a configured
rate in calls per second. The rate SHALL default to 0.2. Its configuration SHALL state
the worst-case full refresh time at 50,000 buckets for 0.2, 1 and 5 calls per second.

Garage's load from the exporter SHALL be set by the rate alone, whatever the number of
buckets.

#### Scenario: Load does not grow with buckets

- **WHEN** the number of buckets grows tenfold
- **THEN** the exporter makes size calls at the same rate as before

### Requirement: Recently written buckets are read first, and no bucket is starved

The exporter SHALL track, for each bucket, when it was last read and when it was last
written to. A bucket SHALL count as changed when it has been written to since it was last
read.

Each read SHALL alternate between two choices:
- the changed bucket that was read longest ago;
- the bucket, changed or not, that was read longest ago.

When no bucket is changed, the first choice SHALL be skipped in favor of the second, so
no read is ever wasted. A bucket written to many times between two reads SHALL need only
one read.

Every bucket SHALL therefore be read at least once per `2 × buckets ÷ rate` seconds,
however much write activity there is.

#### Scenario: A busy bucket is refreshed promptly

- **WHEN** a bucket receives writes and few other buckets have changed
- **THEN** it is read within a few calls after its writes are noticed

#### Scenario: Idle buckets are not starved

- **WHEN** more buckets change between reads than the rate can keep up with
- **THEN** every bucket, including those never written to, is still read at least once
  per `2 × buckets ÷ rate` seconds

#### Scenario: A quiet platform reads every bucket in turn

- **WHEN** no bucket has been written to
- **THEN** every read goes to the bucket read longest ago

### Requirement: Write activity comes from Garage's own request log

The exporter SHALL learn which buckets were written to from the requests Garage itself
logs: any `PUT`, `POST` or `DELETE` addressed to a bucket. It SHALL do so whether the
request reached Garage through the public endpoint or from inside the cluster. A request
addressed to a bucket by Garage's internal identifier SHALL be attributed to that
bucket's alias.

The exporter SHALL keep a position in that log and advance it only after a successful
read of it, so a period the log could not be read is re-read later rather than skipped.

A request may be logged for a bucket that it did not change, or that it was not allowed
to reach. This SHALL cost at most an extra read of that bucket: whatever the log reports,
it SHALL only change the order of reads, never their rate.

#### Scenario: An in-cluster write is noticed

- **WHEN** a deployment writes to its bucket from inside the cluster
- **THEN** that bucket is marked changed

#### Scenario: Requests to other buckets cannot raise the load

- **WHEN** a client sends many requests naming buckets it cannot access
- **THEN** those buckets may be read sooner, but no extra reads are made

### Requirement: A broken activity signal degrades to reading in turn

The exporter SHALL detect when the request log stops reflecting writes. That is, when
Garage's own count of write requests has increased over an interval and the log reports
none. While the signal is broken or unreadable, the exporter SHALL read buckets in
longest-ago order only, at the same rate, and SHALL publish that the signal is broken.

#### Scenario: Log format change

- **WHEN** a Garage upgrade changes the request log so writes are no longer recognized
- **THEN** the exporter reports the activity signal as broken, keeps reading every
  bucket in turn, and its load on Garage is unchanged

### Requirement: Sizes are published with a liveness signal

The exporter SHALL publish, for each bucket it has read, the bytes of the bucket's
completed objects as of its last read, labeled with the bucket's alias. It SHALL also
publish, for as long as it runs, the number of buckets it knows, including when that
number is zero. That is what tells a reader the exporter was running.

A bucket's last known size SHALL keep being published until the bucket is read again or
disappears from the bucket list. This holds when reads fail: a size is never replaced by
zero or dropped for being old.

The exporter SHALL publish when it last read Garage successfully, and how many reads
have failed, so an operator can tell stale sizes from fresh ones.

#### Scenario: Garage unreachable for a while

- **WHEN** Garage cannot be reached for ten minutes
- **THEN** the last known sizes stay published, and the failures and the time of the
  last successful read show the gap

#### Scenario: An environment with no buckets

- **WHEN** an environment holds no deployment buckets
- **THEN** the exporter still publishes a bucket count of zero

### Requirement: A restart does not forget sizes

On start, the exporter SHALL recover each bucket's last published size from Prometheus,
as far back as Prometheus retains it, and publish it until that bucket is read again.
Recovered sizes SHALL count as the oldest readings, so the regular reading order
refreshes them first.

#### Scenario: Restart with many idle buckets

- **WHEN** the exporter restarts in an environment with thousands of idle buckets
- **THEN** their sizes are published again at once, from Prometheus, rather than only
  after each has been read

### Requirement: The exporter holds read-only, size-scoped credentials

The exporter SHALL authenticate to Garage with an admin token limited to listing buckets
and reading a bucket's information. It SHALL NOT hold Garage's master admin token, its
RPC secret, any S3 access key, or any database credential.

The exporter's published sizes SHALL be reachable inside the cluster only.

#### Scenario: Token scope

- **WHEN** the exporter's token is used for any Garage admin operation other than
  listing buckets or reading a bucket's information
- **THEN** Garage refuses it
