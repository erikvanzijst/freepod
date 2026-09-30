# cli-log Specification

## Purpose

The `freepod log` command: which deployment it reads without being told, where its output goes
and why, how it behaves when the application is quiet rather than broken, and what it costs the
client package to exist.

## Requirements

### Requirement: The command reads the project's deployment

The client SHALL resolve the deployment to read from the project in the working directory,
in the same way the other project-scoped commands do, so that `freepod log` in a project
directory needs no arguments.

Where no project file exists, or the project records no deployment, the client SHALL say
so plainly and SHALL NOT guess at a deployment from the account's other deployments.

Where the project records a deployment on an environment other than the one targeted, the
client SHALL name the environment that deployment lives on rather than report that there
is nothing to read, which would send the user to deploy a project that already has a
deployment.

#### Scenario: Reading from a project directory

- **WHEN** `freepod log` runs in a directory whose project records a deployment
- **THEN** that deployment's output is streamed with no arguments given

#### Scenario: Outside a project

- **WHEN** `freepod log` runs where no project file exists
- **THEN** the client reports that there is no deployment to read and streams nothing

#### Scenario: A deployment on another environment is named

- **WHEN** `freepod log` targets one environment and the project records its deployment
  on another
- **THEN** the client names the environment that deployment lives on and streams nothing

### Requirement: Output goes to stdout and status goes to stderr

The client SHALL write the application's log lines to **stdout**, and SHALL write its own
narration — connection notices, the release a stream is following, warnings and errors — to
**stderr**.

This is the opposite split from `freepod deploy`, and deliberately so. There, the build log is
the platform narrating its progress towards a result, so it goes to stderr and leaves stdout for
the address. Here the log lines *are* the result: the user asked for them, and they must survive
`freepod log > app.log` and a pipe into `grep`.

The client SHALL NOT interleave its own narration into stdout, so that a redirected stream
contains the application's output and nothing the client added.

#### Scenario: Redirecting the output

- **WHEN** the output is redirected to a file
- **THEN** the file contains the application's log lines and no client narration

#### Scenario: Piping to a filter

- **WHEN** the output is piped to another program
- **THEN** that program receives only the application's log lines

### Requirement: Following is explicit, and pinning works on every product

The client SHALL support a follow mode that keeps the stream open and prints lines as they
arrive, and SHALL exit cleanly on interrupt without implying anything happened to the
deployment.

In follow mode the client SHALL continue across a redeploy, because the user is watching an
application rather than a container, and a stream that ended silently when the application
restarted would read as the application having stopped.

The client SHALL be able to pin the read to a single release by its number, including a release
that failed and whose pods no longer exist, on a deployment of any product.

#### Scenario: Interrupting a follow

- **WHEN** the user interrupts a followed stream
- **THEN** the client exits without suggesting the deployment was affected

#### Scenario: A redeploy during a follow

- **WHEN** a new release becomes live while the user is following
- **THEN** the stream continues with the new release's output

#### Scenario: Reading a failed release

- **WHEN** the user asks for the log of a release that failed and was rolled back
- **THEN** that release's output is printed

#### Scenario: Pinning on a curated product

- **WHEN** the user pins to a release of a deployment of a curated product
- **THEN** that release's output is printed

### Requirement: Timestamps are available but not imposed

The client SHALL support prepending each line's timestamp to the output, behind a flag, and that
flag SHALL default to **off**.

Off by default because many applications already timestamp their own output, and prepending a
second one yields a line bearing two dates — worse than none for a reader and worse for anything
parsing. The platform carries the timestamp regardless; only rendering it is optional.

The default SHALL NOT differ between a followed read and a bounded one. Emitting differently
shaped lines depending on the mode would break exactly what a downstream pipe relies on, however
reasonable the distinction seems.

Where more than one optional prefix is rendered, prefixes SHALL appear in a fixed order, so that
output remains splittable by position.

#### Scenario: The default output

- **WHEN** the log is read without asking for timestamps
- **THEN** the application's lines are printed as the application wrote them

#### Scenario: Timestamps requested

- **WHEN** the log is read with timestamps requested
- **THEN** each line is prefixed with the time the platform recorded for it

#### Scenario: An application that timestamps its own output

- **WHEN** such an application's log is read with the default settings
- **THEN** each line carries exactly one timestamp, the application's own

#### Scenario: The mode does not change the shape

- **WHEN** the same deployment is read once followed and once bounded, with the same flags
- **THEN** the lines are shaped identically

### Requirement: A quiet application does not end the stream

The client SHALL NOT apply its default request timeout to a followed stream. That default is a
bound on how long a request may take to answer, and a followed stream is not trying to finish;
applying it would disconnect any application that stays quiet for longer than an ordinary request
should take.

The client SHALL instead treat the **absence of the platform's keepalive** as the disconnection
signal, not the absence of application output. An application that says nothing is working
normally; a platform that says nothing has gone away, and only the second is a fault.

The client SHALL discard keepalives without emitting them, so that a quiet period leaves no trace
in redirected output.

#### Scenario: A long quiet period

- **WHEN** a followed application produces no output for far longer than the client's default
  request timeout
- **THEN** the stream stays open and printing resumes when the application writes again

#### Scenario: The connection is genuinely lost

- **WHEN** keepalives stop arriving
- **THEN** the client treats the stream as interrupted rather than as the application having
  finished

#### Scenario: Keepalives never reach the output

- **WHEN** output is redirected to a file across a quiet period
- **THEN** the file contains only the application's lines

### Requirement: A followed stream reconnects from where it stopped

The client SHALL retain the timestamp of the most recent event it received, and on an interrupted
follow SHALL reconnect from it rather than restarting at the present. Restarting at the present
would silently lose everything written during the outage — which is when the interesting output
tends to happen.

The client SHALL resume from the same timestamp field it renders, rather than tracking a separate
resume value, so that what it displays and what it resumes from cannot disagree.

Reconnection SHALL be bounded, SHALL back off between attempts, and SHALL be reported on stderr
so that a gap in a followed stream is never silent. On exhausting its attempts the client SHALL
report the interruption rather than exit as though the application had finished.

Because resumption is at-least-once, the client MAY print a line it has already printed after a
reconnect. It SHALL NOT suppress lines to avoid this, since suppression risks discarding a line
that was genuinely new.

#### Scenario: A brief network interruption

- **WHEN** a followed stream drops and reconnects
- **THEN** output written during the interruption is printed
- **AND** the reconnection is noted on stderr

#### Scenario: The platform stays unreachable

- **WHEN** reconnection attempts are exhausted
- **THEN** the client reports the stream as interrupted and exits non-zero
- **AND** does not imply the application stopped

#### Scenario: A duplicated line after reconnecting

- **WHEN** the platform re-delivers a line the client already printed
- **THEN** the client prints it rather than dropping lines to deduplicate

### Requirement: Silence is distinguished from failure

The client SHALL distinguish an application that has produced no output from a platform that
could not answer, and SHALL NOT present the second as the first.

Where the log store is unavailable, the client SHALL report a platform condition. Where the
application genuinely produced nothing, the client SHALL say so on stderr rather than exiting
silently, so that an empty result is legible as an answer rather than as a broken command.

#### Scenario: The log store is unavailable

- **WHEN** the platform reports that it cannot reach the log store
- **THEN** the client reports a platform condition and does not claim the application was silent

#### Scenario: The application has written nothing

- **WHEN** the deployment's pods have produced no output
- **THEN** the client says so on stderr and exits successfully

### Requirement: The command adds no dependency to the client package

The command SHALL be implemented over the client's existing HTTP transport and SHALL NOT add a
package dependency.

It SHALL reuse the existing API client so that authentication, token refresh and the platform's
status-code contract behave identically to every other command, rather than being reimplemented
for one endpoint.

#### Scenario: The package's dependencies are unchanged

- **WHEN** the command ships
- **THEN** the client package declares no dependency it did not declare before

#### Scenario: An expired credential

- **WHEN** the access token has expired as the command runs
- **THEN** the credential is refreshed by the same path every other command uses, and the stream
  proceeds
