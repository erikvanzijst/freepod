# garage-bucket-provisioning Specification

## Purpose
How the platform's own bucket, access key and object expiry are created and scoped on an
environment's Garage instance, and how the resulting credentials reach the Caelus API — given
that Garage has no IAM.
## Requirements
### Requirement: Buckets and access keys are provisioned through Garage's native mechanism

Garage implements **no IAM, no bucket policies and no ACLs**. Access control is a Garage-native
per-access-key-per-bucket permission model, driven by the `garage` CLI or by the Garage admin
API. There is therefore no S3-policy-shaped Terraform resource to use, and the standard AWS
provider's IAM resources are inapplicable.

The module SHALL name an explicit, repeatable bootstrap mechanism for creating buckets, creating
access keys and granting per-bucket permissions, and SHALL document which parts are Terraform-
managed and which are operator-run. The awkwardness is owned explicitly rather than left to be
rediscovered: whichever mechanism is chosen, the documentation MUST state how to re-run it
safely and what drifts if someone edits Garage state by hand.

Where Garage's admin API is used, the token SHALL be a scoped token limited to the bucket and
key operations actually needed, with an expiry where the mechanism supports one — not the
cluster-wide master admin token.

#### Scenario: Provisioning mechanism is named and documented

- **WHEN** the module's source and `tf/app/README.md` are read
- **THEN** the bucket and access-key provisioning mechanism is named explicitly
- **AND** the split between Terraform-managed and operator-run steps is stated

#### Scenario: Provisioning is idempotent

- **WHEN** the provisioning procedure is run a second time against an already-provisioned Garage
- **THEN** it completes without error
- **AND** it does not rotate or invalidate the existing access keys

#### Scenario: A key can only reach its own bucket

- **WHEN** an access key provisioned for one bucket is used against a different bucket
- **THEN** the request is denied
- **AND** no object is read, written or listed

### Requirement: Bucket lifecycle expiration is configured at provisioning time

Objects in this store are ephemeral: written once, read once, and worthless within roughly a
day. Each provisioned bucket SHALL carry an S3 lifecycle configuration that expires objects
after a configurable age, applied as part of bucket provisioning rather than added afterwards.

Garage implements exactly two lifecycle actions — `Expiration` and
`AbortIncompleteMultipartUpload` — and both SHALL be used: expiration reclaims completed
objects, and aborting incomplete multipart uploads reclaims the parts left behind by a client
that disconnected mid-upload. Parts from abandoned multipart uploads consume disk without ever
appearing as objects, so omitting the second rule leaks storage invisibly on a node with a
history of disk pressure.

The expiry age SHALL be configurable through Terraform, not hardcoded.

Declarative expiry is the reason this design needs **no reaper CronJob and no cleanup code**:
storage reclamation is a property of the bucket, so it cannot be forgotten by a caller, skipped
by a failed job, or lost when the consuming code is refactored.

#### Scenario: Lifecycle rules exist on a provisioned bucket

- **WHEN** the lifecycle configuration of a provisioned bucket is read
- **THEN** it contains an `Expiration` rule with the configured age in days
- **AND** it contains an `AbortIncompleteMultipartUpload` rule

#### Scenario: Expired objects are removed without external help

- **WHEN** an object remains in the bucket past the configured expiry age
- **THEN** Garage deletes it
- **AND** no CronJob, worker task or application code participates in the deletion

#### Scenario: Expiry age is configurable

- **WHEN** the Terraform module is inspected
- **THEN** the expiry age is supplied by a module variable with a documented default

### Requirement: The Caelus API receives S3 credentials via a Kubernetes Secret

The Caelus API needs the S3 endpoint and an access key in order to mint presigned URLs. These
values SHALL be delivered as a Kubernetes Secret consumed by the API container through
`env_from`, following the existing `caelus-db` pattern in `tf/app/caelus/`.

The Secret SHALL carry, at minimum: the S3 endpoint URL, the region, the platform bucket name,
the access key ID and the secret access key.

The instance and the API are in the same root module and workspace, so the credentials SHALL be
wired from the Garage module's outputs into the API module directly. The operator SHALL NOT
transfer them by hand.

Secret values MUST NOT appear in tracked files, in Terraform outputs printed by default, or in
pod logs.

#### Scenario: The API pod receives the credentials

- **WHEN** the Caelus API pod spec is inspected
- **THEN** it references the S3 credentials Secret via `env_from`
- **AND** the pod's environment contains the endpoint, region, bucket, access key ID and secret
  access key

#### Scenario: Each environment receives only its own credentials

- **WHEN** the dev and prod API deployments are compared
- **THEN** each references its own environment's instance, endpoint and access key
- **AND** neither carries a credential the other environment's instance accepts

#### Scenario: Credentials are absent from version control

- **WHEN** the repository is searched for the generated access key ID and secret
- **THEN** neither appears in any tracked file

### Requirement: The API exposes S3 connection settings as CAELUS_ configuration

`api/app/config.py` SHALL define settings for the S3 endpoint, region, bucket, access key ID,
secret access key and the presigned-URL expiry, following the module's existing
`CAELUS_`-prefixed `pydantic-settings` convention, so the values delivered by the Secret are
read through the same typed settings object as every other configuration value rather than via
ad-hoc `os.environ` access.

Settings SHALL have safe defaults or be explicitly optional, so that local development and the
existing test suite run without a configured object store. Secret-bearing settings MUST NOT have
a real credential as their default.

The API's *use* of these settings — the endpoints that mint presigned URLs — is out of scope for
this change; only the configuration surface is added.

#### Scenario: Settings are defined with the CAELUS_ prefix

- **WHEN** `api/app/config.py` is inspected
- **THEN** settings exist for the S3 endpoint, region, bucket, access key ID, secret access key
  and presigned-URL expiry
- **AND** each is populated from the correspondingly named `CAELUS_*` environment variable

#### Scenario: Tests and local dev run without object-store configuration

- **WHEN** the API test suite is run with no S3 environment variables set
- **THEN** settings load successfully
- **AND** no test fails for want of object-store configuration

#### Scenario: No credential is baked in as a default

- **WHEN** the default values of the S3 settings are inspected
- **THEN** the access key ID and secret access key default to empty or unset values

### Requirement: Each instance provisions one platform bucket and access key

Each Garage instance serves exactly one environment, so the platform's own bucket and access
key SHALL NOT be qualified by environment. Every instance SHALL have one platform bucket named
`artifacts` and one platform access key named `caelus-api`, granted read and write on that
bucket only. Tenant buckets are prefixed `dep-` (see `deployment-object-storage`), so the
platform bucket cannot collide with one.

The names SHALL be defined once in the Terraform module and handed to the provisioning Job, not
hardcoded independently in several places.

#### Scenario: One platform bucket per instance

- **WHEN** an instance's buckets are listed
- **THEN** exactly one bucket that is not prefixed `dep-` exists, named `artifacts`
- **AND** a key named `caelus-api` has read and write on it and on no other bucket

#### Scenario: Naming is defined once

- **WHEN** the Terraform module is inspected
- **THEN** the platform bucket and key names come from one definition passed to the
  provisioning Job and used for the module's outputs

### Requirement: A change to the API's S3 credentials restarts their consumers

Every Deployment that reads the API's S3 credentials Secret through `env_from` — the API, the
reconcile worker and the build worker — SHALL carry an annotation derived from the Secret's
content, so that changing the endpoint, bucket or key rolls those pods in the same apply.

#### Scenario: Rotating the key rolls the pods

- **WHEN** the S3 credentials Secret's content changes in a `terraform apply`
- **THEN** the API, reconcile worker and build worker Deployments roll
- **AND** their new pods carry the new values
