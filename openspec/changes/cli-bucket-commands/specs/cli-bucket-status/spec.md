## Purpose

Gives the `freepod` client a `bucket` command group, beside `db`, and its `status` member,
which reports the project deployment's bucket: which bucket it is, where it is served, the
credentials that reach it, and how much of its limits it uses.

## ADDED Requirements

### Requirement: `freepod bucket status` reports the deployment's bucket
The client MUST provide a `bucket` command group with a `status` subcommand that reads the platform's bucket details for the deployment recorded in the project file and reports the bucket name, the S3 endpoint, the region, the access key id, the secret access key, the bucket's size against its size limit, and its object count against its object limit.

The command MUST resolve its deployment the same way the other project-scoped commands do, from the project file and refusing the same ways, and MUST NOT accept a deployment named on the command line.

#### Scenario: Reporting a provisioned bucket
- **WHEN** a developer runs `freepod bucket status` in a project whose deployment has object storage
- **THEN** the bucket name, endpoint, region, access key id, masked secret, size against limit and object count against limit are reported

#### Scenario: No deployment
- **WHEN** the command runs in a directory whose project file records no deployment
- **THEN** it fails as the other project-scoped commands do

### Requirement: The secret is masked unless it is asked for
`freepod bucket status` MUST mask the secret access key in its default output and MUST print it only when the invocation passes `--show-secret`. The masked output MUST show that a value exists and how to reveal it, and the mask MUST NOT reveal the secret's length.

When the platform withholds the secret because the caller is not the owner, the command MUST say so, and `--show-secret` MUST NOT suggest it can reveal it.

#### Scenario: Default output masks
- **WHEN** a developer runs `freepod bucket status`
- **THEN** the output does not contain the secret
- **AND** it says how to reveal it

#### Scenario: Explicit reveal
- **WHEN** a developer runs `freepod bucket status --show-secret`
- **THEN** the secret is printed

#### Scenario: Withheld secret
- **WHEN** an administrator runs the command against a deployment they do not own
- **THEN** the output states that the secret is withheld from anyone but the owner

### Requirement: Usage is reported against the bucket's limits
The command MUST report size and object count each against its limit, so the reader can see how close the bucket is to refusing writes.

#### Scenario: Usage against limits
- **WHEN** the bucket holds objects
- **THEN** the output reports the bytes used against the size limit and the object count against the object limit

### Requirement: A product without object storage is not an error
When the platform reports that the deployment has no bucket, `freepod bucket status` MUST say so plainly and exit successfully.

#### Scenario: Product without a bucket
- **WHEN** a developer runs `freepod bucket status` in a project whose product has no object storage
- **THEN** the command reports that this deployment has no bucket and exits successfully
