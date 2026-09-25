# cli-build-submission Specification

## Purpose
Getting a packed project onto the platform and watching it become an image: claiming an
upload slot, submitting the archive, queuing a build, and following its output until it
reaches a terminal state.
## Requirements
### Requirement: The archive is uploaded with the credentials the platform mints

The client SHALL obtain an upload slot from the platform and submit the archive as a
form upload to the address the slot names, sending every field the slot returns
unaltered and in the order given, with the file part last. It SHALL NOT alter, reorder,
or supplement those fields, and SHALL NOT derive an upload address of its own.

The slot SHALL be obtained **after** the archive has been packed, because a slot expires
and a large archive on a slow connection can outlive it. Obtaining a slot persists
nothing, so an unused slot costs nothing.

#### Scenario: The archive reaches the object store

- **WHEN** the client submits the archive with the slot's fields
- **THEN** the object store accepts it

#### Scenario: Altered upload fields are rejected rather than silently accepted

- **WHEN** the fields returned with a slot are modified before submission
- **THEN** the object store refuses the upload

#### Scenario: The slot is minted after packing

- **WHEN** a deploy packs a project and uploads it
- **THEN** the upload slot is requested after the archive exists

### Requirement: An expired or refused slot is retried once with a fresh slot

When the object store refuses the upload with a forbidden status, the client SHALL
obtain a new slot and retry the submission once. If the retry is also refused, it SHALL
fail and report the object store's response.

#### Scenario: An expired slot is replaced transparently

- **WHEN** the upload is refused because the slot has expired
- **THEN** the client obtains a fresh slot and resubmits the same archive
- **AND** the deploy proceeds when the retry succeeds

#### Scenario: A repeatedly refused upload fails clearly

- **WHEN** the retry with a fresh slot is also refused
- **THEN** the client stops and reports the store's response

### Requirement: A build is created from the uploaded artifact

The client SHALL create a build for the project's recorded deployment, referencing the
uploaded artifact identifier and supplying that identifier alone. It SHALL NOT attempt to
specify the build's owner, which is the deployment's.

#### Scenario: A build is queued

- **WHEN** the client creates a build for a successfully uploaded artifact
- **THEN** the platform returns a build in a queued state, belonging to the project's deployment

### Requirement: An in-flight build is re-attached rather than duplicated

When the platform answers build creation by returning an existing build rather than
creating a new one, the client SHALL follow that build and SHALL state that it re-attached
to work already in progress.

#### Scenario: A repeated deploy attaches to the running build

- **WHEN** the platform returns an already-running build for the same artifact
- **THEN** the client reports that it is following the existing build
- **AND** does not create a second one

### Requirement: Build output is streamed while the build runs

The client SHALL follow the build's output incrementally, requesting only the bytes
appended since its last read, and SHALL write each chunk to standard output as it
arrives rather than accumulating it. It SHALL read the build's current status from the
response accompanying every chunk, and stop when that status is terminal.

A request for a range beginning at the current end of the output is the normal state
while a build runs and SHALL NOT be treated as an error. Offsets SHALL be tracked in
bytes.

While the build is queued and has produced no output, the client SHALL say so rather
than appearing to hang. Polling SHALL back off while no output is arriving.

#### Scenario: Output appears while the build runs

- **WHEN** the build writes output
- **THEN** the client displays it as it arrives, without waiting for the build to finish

#### Scenario: An empty incremental read is not an error

- **WHEN** a read requests bytes from the current end of the output
- **THEN** the client treats the empty result as normal and continues polling

#### Scenario: No output is read twice

- **WHEN** the client polls repeatedly during a build
- **THEN** each byte of output is displayed exactly once

#### Scenario: A queued build reports that it is waiting

- **WHEN** the build has not started and has produced no output
- **THEN** the client reports that the build is queued

#### Scenario: Streaming stops at a terminal status

- **WHEN** the status accompanying a chunk is `succeeded`, `failed`, or `canceled`
- **THEN** the client stops polling without issuing a further status request

### Requirement: Interrupting the client does not cancel the build

When the user interrupts while a build is being followed, the client SHALL state that
the build continues on the platform and SHALL report its identifier, rather than
implying the build was canceled.

#### Scenario: Interruption is explained accurately

- **WHEN** the user interrupts while following a build
- **THEN** the client reports that the build continues and names its identifier

### Requirement: A build that does not succeed stops the deploy

When a build reaches a terminal status other than success, the client SHALL stop, report
the outcome, and SHALL NOT release anything. When a build succeeds, the client SHALL
read the resulting image reference from the build record.

#### Scenario: A failed build stops before release

- **WHEN** the build ends with a failed status
- **THEN** the client reports the failure and does not create or update a deployment

#### Scenario: A successful build yields an image reference

- **WHEN** the build ends with a successful status
- **THEN** the client reads the build's image reference for the release step
