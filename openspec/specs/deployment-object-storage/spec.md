# deployment-object-storage Specification

## Purpose
How a private S3 bucket and a dedicated access key are provisioned, scoped, quota-limited and
reclaimed for an individual deployment on its environment's Garage instance — and what the isolation
between two deployments' buckets actually rests on, given that Garage has no IAM.
## Requirements
### Requirement: Object storage is provisioned per deployment, opt-in per product

A deployment SHALL be provisioned with object storage when, and only when, its product
template declares the opt-in. The decision is **product-level platform policy, not a tenant
choice**: it SHALL NOT be expressed in the tenant-facing values schema, SHALL NOT appear as a
field on the deployment form, and SHALL NOT be settable through user values.

Provisioning SHALL occur as part of the normal apply path, before the Helm release is
installed or upgraded, so that no pod ever starts expecting credentials that do not yet exist.

A deployment whose product does not opt in SHALL have no bucket, no access key and no
credentials Secret, and its Helm values SHALL carry no storage block.

#### Scenario: A product that opts in

- **WHEN** a deployment of a product whose template declares object storage as enabled is applied
- **THEN** a bucket and an access key exist for that deployment
- **AND** the credentials Secret exists in the deployment's namespace before the Helm release
  is installed or upgraded

#### Scenario: A product that does not opt in

- **WHEN** a deployment of a product whose template does not declare object storage is applied
- **THEN** no bucket, access key or credentials Secret is created for it
- **AND** the merged Helm values contain no storage block

#### Scenario: A tenant cannot opt themselves in

- **WHEN** a tenant supplies user values that attempt to enable storage
- **THEN** the values are rejected or ignored
- **AND** no bucket is provisioned as a result

### Requirement: The bucket is named for the deployment and the name is a global alias

Each deployment's bucket SHALL carry a Garage **global alias** derived from the deployment's
immutable identifier, in the form `dep-<deployment-id>`.

The deployment identifier is a randomly generated UUID and is the platform's own primary key.
It is unguessable, globally unique, stable for the life of the deployment, and never reused —
so it needs no separate registry, no uniqueness check and no collision handling. A **local**
(key-scoped) alias SHALL NOT be used as the sole name: a local alias is deleted with its key,
which would leave a deleted deployment's bucket anonymous and untraceable exactly when
reclamation needs to identify it.

The `dep-` prefix is required. It SHALL be what distinguishes a deployment's bucket from every
other bucket on the instance, so that tooling selects deployment buckets explicitly
rather than by inferring intent from the shape of a name.

The naming scheme SHALL NOT be changed to anything derivable from tenant-visible attributes
such as user, email, product or hostname. Garage distinguishes a bucket that exists but is
forbidden from one that does not exist, which makes any bucket name an existence oracle; that
is harmless against a random UUID and is not harmless against a guessable name.

#### Scenario: Bucket naming

- **WHEN** the bucket provisioned for a deployment is inspected
- **THEN** it carries a global alias of the form `dep-<deployment-id>`
- **AND** the identifier matches the deployment's primary key exactly

#### Scenario: The name survives credential revocation

- **WHEN** a deployment's access key has been deleted
- **THEN** the bucket still carries its `dep-<deployment-id>` global alias
- **AND** the bucket can still be located by that alias

### Requirement: Each deployment receives its own access key, scoped to its own bucket alone

Every deployment SHALL receive a dedicated access key. A key SHALL NOT be shared between two
deployments, nor between a deployment and the platform's own artifact-store credentials.

The key SHALL be granted read and write on that deployment's bucket and on no other bucket.

Isolation between two deployments' buckets rests on **Garage's per-key-per-bucket permission
grants**, and SHALL be stated as such rather than as a property of bucket naming. Garage's S3
API resolves a bucket by its raw internal identifier as well as by alias, so a bucket is
addressable by any caller who learns that identifier; what denies the request is the absence
of a permission grant. A key SHALL therefore never be granted a permission it does not need,
and the fact that a name is unguessable SHALL NOT be relied on as an access control.

#### Scenario: A key reaches its own bucket

- **WHEN** a deployment's key reads, writes or lists its own bucket
- **THEN** the request succeeds

#### Scenario: A key cannot reach another deployment's bucket by name

- **WHEN** a deployment's key addresses another deployment's bucket by its global alias
- **THEN** the request is denied

#### Scenario: A key cannot reach another deployment's bucket by internal identifier

- **WHEN** a deployment's key addresses another deployment's bucket by its raw internal
  identifier, bypassing aliases entirely
- **THEN** the request is denied

#### Scenario: A key cannot enumerate other deployments' buckets

- **WHEN** a deployment's key lists buckets
- **THEN** only its own bucket is returned
- **AND** no other deployment's bucket name or identifier is disclosed

### Requirement: The bucket carries a storage quota and the quota is fail-closed

Each provisioned bucket SHALL carry a storage quota enforced by the object store itself, so
that exceeding it is refused at write time rather than detected afterwards by platform
accounting.

The quota SHALL be derived from the deployment's plan. Every plan declares a storage
allowance, so a storage-enabled deployment always has one to read.

There SHALL be no platform default standing in for a missing plan quota. A storage-enabled
deployment whose quota cannot be resolved — the plan's allowance is absent or zero, or the
deployment has no subscription at all — SHALL **fail to provision**, surfacing as a
deployment error. It SHALL NOT receive an unbounded bucket, and it SHALL NOT silently receive
a fallback allowance that no plan authorized.

This is deliberately the opposite of how plan storage is projected into Helm values, where an
absent quota means a chart falls back to its own default. A chart's default is written by the
platform and is bounded; an unset quota on a shared object store is neither.

Quotas SHALL be re-asserted on every apply, so that a plan change takes effect on the next
reconcile without a separate migration.

Each bucket SHALL also be provisioned with a cross-origin policy permitting browser access,
applied by the platform, so that a tenant application can accept browser-direct uploads without
configuring anything. The policy SHALL expose the `ETag` response header, which multipart
uploads require and which is hidden from browsers by default.

A tenant SHALL NOT be able to set this policy themselves, and SHALL NOT be required to.

#### Scenario: Plan defines a storage quota

- **WHEN** a deployment whose plan defines a storage quota is applied
- **THEN** its bucket carries a quota equal to the plan's value

#### Scenario: Plan defines no storage quota

- **WHEN** a storage-enabled deployment whose plan has an absent or zero allowance is applied
- **THEN** provisioning fails with an error naming the unresolvable quota
- **AND** no bucket is left reachable by a credential without a quota on it

#### Scenario: Deployment has no subscription

- **WHEN** a storage-enabled deployment with no subscription at all is applied
- **THEN** provisioning fails with an error naming the missing subscription
- **AND** the deployment does not receive an unbounded bucket

#### Scenario: A product that does not opt in is unaffected

- **WHEN** a deployment whose product does not enable storage has no subscription, or a plan
  with a zero allowance
- **THEN** it reconciles normally
- **AND** no quota is resolved for it, because no bucket is provisioned

#### Scenario: Plan quota changes

- **WHEN** a deployment's plan quota changes and the deployment is reconciled
- **THEN** the bucket's quota reflects the new value

#### Scenario: A browser preflight against a provisioned bucket

- **WHEN** a browser issues a cross-origin preflight for an upload to a provisioned bucket
- **THEN** the store answers with a success status and the cross-origin headers permitting it
- **AND** the response exposes the `ETag` header

#### Scenario: Writing past the quota

- **WHEN** a tenant writes objects exceeding the bucket's quota
- **THEN** the object store refuses the write
- **AND** no platform code participates in detecting or enforcing the overage

### Requirement: The bucket defaults to aborting abandoned multipart uploads

A bucket that has no lifecycle configuration SHALL be given one rule that aborts incomplete
multipart uploads one day after initiation. Parts of an abandoned upload consume disk while
appearing in neither a bucket listing nor the bucket's measured size, so without the rule they
escape both the quota and metering indefinitely.

The rule is a default, not an enforced policy. A tenant's key can replace the bucket's whole
lifecycle configuration, so provisioning SHALL NOT overwrite a configuration that is present:
the default SHALL only be applied when the bucket has none. A live bucket SHALL NOT be given an
`Expiration` rule.

#### Scenario: New bucket

- **WHEN** a storage-enabled deployment is provisioned
- **THEN** its bucket carries an `AbortIncompleteMultipartUpload` rule of one day
- **AND** no `Expiration` rule

#### Scenario: The tenant has set their own lifecycle rules

- **GIVEN** a tenant has replaced their bucket's lifecycle configuration
- **WHEN** the deployment is reconciled
- **THEN** the tenant's configuration is left unchanged

#### Scenario: The tenant has removed their lifecycle rules

- **GIVEN** a tenant has deleted their bucket's lifecycle configuration
- **WHEN** the deployment is reconciled
- **THEN** the default abort rule is applied again

### Requirement: Provisioning is idempotent and resumable at each step

Provisioning SHALL read before it writes at every step, so that reconciling an
already-provisioned deployment changes nothing and never rotates a live credential.

Each step — key, bucket, permission grant, quota — SHALL be verified independently. The
existence of one step SHALL NOT be taken as evidence that a later step completed: a run
interrupted between creating a key and creating a bucket leaves a key with no bucket, and the
next run SHALL complete the remaining steps rather than concluding that provisioning is done.

#### Scenario: Reconciling an already-provisioned deployment

- **WHEN** a deployment that already has a bucket and key is reconciled
- **THEN** no new bucket or key is created
- **AND** the existing access key is not rotated
- **AND** the credentials in the deployment's namespace are unchanged

#### Scenario: Resuming after an interruption

- **GIVEN** a previous run created the access key but not the bucket
- **WHEN** the deployment is reconciled again
- **THEN** the bucket is created and the permission grant applied
- **AND** the existing access key is reused rather than replaced

#### Scenario: Repairing a removed permission grant

- **GIVEN** a deployment's permission grant has been removed out of band
- **WHEN** the deployment is reconciled
- **THEN** the grant is restored

### Requirement: Deletion revokes access synchronously and delegates reclamation to the store

When a deployment is deleted, its access key SHALL be deleted as part of the delete
reconcile. Revocation is the security-relevant act, it is total, and it SHALL NOT be deferred
to a background process.

Reclamation of the objects SHALL be delegated to the object store by setting a short
object-expiry lifecycle rule on the bucket. The reconciler SHALL NOT enumerate and delete the
bucket's objects synchronously: the object count is unbounded and tenant-controlled, and the
delete reconcile runs under a fixed wall-clock budget.

The key SHALL be deleted **before** the expiry rule is set. A key with write access can replace
its bucket's lifecycle configuration, so setting the rule while the key is still live leaves a
window in which the tenant can remove it.

The bucket itself SHALL NOT be deleted during the delete reconcile. The store refuses to
delete a non-empty bucket, and the bucket is not empty at that moment.

A drained bucket that no key can reach SHALL be treated as acceptable residue. It holds
metadata only, and its global alias names the deployment it belonged to, so it remains
attributable indefinitely.

#### Scenario: Access is revoked on delete

- **WHEN** a deployment is deleted
- **THEN** its access key no longer exists
- **AND** no credential anywhere can read or write its bucket

#### Scenario: The key is gone before the expiry rule is set

- **WHEN** a deployment is deleted
- **THEN** its access key is deleted before the object-expiry rule is applied to its bucket
- **AND** no credential exists that could remove the rule afterwards

#### Scenario: Objects are reclaimed without synchronous deletion

- **WHEN** a deployment holding a large number of objects is deleted
- **THEN** the delete reconcile completes within its normal budget
- **AND** the bucket carries an object-expiry lifecycle rule
- **AND** the objects are removed by the object store thereafter

#### Scenario: The expiry window is not a recovery mechanism

- **WHEN** the expiry window is chosen
- **THEN** it is set for prompt reclamation of a constrained shared volume, not to serve as an
  undo for an accidental delete
- **AND** recovery of deleted tenant data relies on backups rather than on objects that have
  not yet expired

#### Scenario: The credentials Secret is removed with the namespace

- **WHEN** a deployment is deleted and its namespace removed
- **THEN** no credentials Secret for it remains in the cluster

### Requirement: The platform authenticates to the object store with a scoped administrative credential

The credential the platform uses to provision buckets and keys SHALL be scoped to the
administrative operations provisioning actually performs, and SHALL NOT be the object store's
master token.

The scope SHALL NOT include the ability to mint or modify administrative tokens, which is
equivalent to unrestricted access.

This credential's blast radius SHALL be recorded honestly rather than implied away: it can
read back the secret of any access key it can see, so compromise of the platform's
provisioning credential is compromise of every tenant bucket. Scoping bounds what else that
credential can do — it cannot read cluster status, alter the cluster layout, or escalate — but
it does not eliminate this exposure, which is inherent to automated provisioning.

#### Scenario: The provisioning credential is scoped

- **WHEN** the credential the platform uses for provisioning is inspected
- **THEN** it is limited to the bucket and key operations provisioning performs
- **AND** it is not the master token
- **AND** it cannot create or modify administrative tokens

#### Scenario: The provisioning credential cannot administer the cluster

- **WHEN** the provisioning credential is used to read cluster status or alter the cluster
  layout
- **THEN** the request is denied

