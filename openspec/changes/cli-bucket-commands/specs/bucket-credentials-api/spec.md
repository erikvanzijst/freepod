## Purpose

A storage-enabled deployment's bucket credentials are minted by the object store and
delivered only into the pod, so the owner cannot reach their own bucket from anywhere else.
This capability exposes them through a deployment-scoped read endpoint, together with the
bucket's live usage, so the owner's client can talk to the bucket directly over the public S3
endpoint and the owner can see how close it is to its limits.

## ADDED Requirements

### Requirement: A deployment-scoped endpoint returns the bucket's connection details
The API MUST provide a read endpoint at `/api/users/{user_id}/deployments/{deployment_id}/bucket`, following the platform's nested-route convention for deployment sub-resources, returning the deployment's bucket name, the S3 endpoint URL, the region, the access key id and the secret access key.

The bucket name MUST be the bucket's `dep-<deployment-id>` global alias. The object store's internal bucket identifier MUST NOT be returned: no client addresses the bucket by it, and isolation does not rest on its secrecy, so there is nothing for it to do in the response.

The endpoint URL and region MUST be the same values the deployment's own pod receives, so that one credential set works identically from the pod and from the owner's machine.

#### Scenario: Owner retrieves connection details
- **WHEN** the owner requests the bucket details of a settled storage-enabled deployment
- **THEN** the response contains the bucket's global alias, the S3 endpoint URL, the region, the access key id and the secret access key

#### Scenario: Details match the pod's
- **WHEN** the response is compared with the object-storage environment of the deployment's application container
- **THEN** the bucket name, endpoint, region, access key id and secret access key are identical

#### Scenario: No internal identifier
- **WHEN** the response is inspected
- **THEN** no field carries the object store's internal bucket identifier

### Requirement: The response carries components, not a composed URL
The response MUST return the bucket's endpoint and name as separate fields and MUST NOT include an object URL, a bucket URL or a presigned URL. Composing addresses and signing requests belong to the client that uses them.

#### Scenario: No composed URL
- **WHEN** the owner reads the bucket details
- **THEN** no field other than the endpoint carries a URL

### Requirement: The response reports live usage unless asked not to
By default the response MUST report the bucket's current size in bytes and object count, read from the object store at request time, together with the size limit and object limit enforced on the bucket.

A request carrying `usage=false` MUST NOT read usage from the object store, and its response MUST make clear that usage was not requested rather than reporting zero. Reading usage costs the object store an authenticated administrative call, so a client that only needs the credentials MUST be able to avoid it.

The limits MUST be the ones the bucket actually carries. The size limit is the plan's storage allowance.

#### Scenario: Usage reported by default
- **WHEN** the owner requests the bucket details without the `usage` parameter
- **THEN** the response reports the bucket's current bytes and object count and its size and object limits

#### Scenario: Usage opted out
- **WHEN** the owner requests the bucket details with `usage=false`
- **THEN** the response contains the connection details
- **AND** it reports that usage was not requested, rather than a size or object count of zero
- **AND** no usage read was made against the object store

#### Scenario: Usage is current
- **WHEN** an object is written to the bucket and the details are then requested with usage
- **THEN** the reported bytes and object count include that object

### Requirement: Absence semantics mirror the database endpoint
The endpoint MUST distinguish "this deployment has no bucket" from a transient error by answering with a not-found response carrying a stable code a client can key on.

A deployment that does not exist, one not owned by the account named in the path, and one that has been deleted MUST all answer identically with the platform's standard not-found, disclosing nothing about a bucket.

A bucket is provisioned during reconcile, before the deployment reaches its ready state. The interval in which it does not yet exist is an interval in which the deployment is not settled, and the endpoint MUST answer it with the same no-bucket code rather than inventing a separate "provisioning" state.

A failure to reach the object store MUST be reported as a server-side error, never as the no-bucket code.

#### Scenario: Product without object storage
- **WHEN** the owner requests the bucket details of a deployment whose product does not opt in to object storage
- **THEN** the response is a not-found carrying the stable no-bucket code

#### Scenario: Deleted deployment
- **WHEN** the owner requests the bucket details of a deleted deployment
- **THEN** the response is the platform's standard not-found, disclosing nothing about the bucket

#### Scenario: Deployment requested under the wrong owner
- **WHEN** an administrator requests a deployment that exists but is not owned by the account named in the path
- **THEN** the response is the platform's standard not-found

#### Scenario: Object store unreachable
- **WHEN** the object store cannot be reached while serving the request
- **THEN** the response is a server-side error and does not carry the no-bucket code

### Requirement: The secret is readable by the owner alone
Reading the bucket details MUST follow the platform's deployment authorization rules: the owner may read them, and a caller who is neither the owner nor an administrator MUST be refused with the platform's standard authorization error.

The **secret access key** MUST be returned only to the owner. An administrator MUST receive the other details without it, and the response MUST say that it was withheld rather than leaving it absent. The secret grants read and write on everything the tenant stores in the bucket, and administrative access exists to operate the platform, not to read tenant data; the database password is withheld on the same grounds.

#### Scenario: Non-owner is refused
- **WHEN** a user who is neither the owner nor an administrator requests another account's bucket details
- **THEN** the request is refused with the platform's standard authorization error

#### Scenario: Administrator reads details without the secret
- **WHEN** an administrator requests another account's bucket details
- **THEN** the response contains the bucket name, endpoint, region, access key id and usage
- **AND** no field contains the secret access key, in any form
- **AND** the response states that the secret was withheld

### Requirement: Reading has no side effects
Reading the bucket details MUST NOT create, rotate or modify a key, a bucket, a permission grant, a quota or a lifecycle rule. It is a read of what provisioning already created.

#### Scenario: Repeated reads return the same credentials
- **WHEN** the owner reads the details twice with no reconcile in between
- **THEN** both responses carry the same access key id and secret

#### Scenario: Reading provisions nothing
- **WHEN** the details are requested for a storage-enabled deployment whose key has been removed out of band
- **THEN** no key is created by the request

### Requirement: The secret is never written to a log
The secret access key MUST NOT appear in application logs, request or response logs, error messages or exception traces, on any path including failures.

#### Scenario: Successful read logs no secret
- **WHEN** the endpoint returns the bucket details
- **THEN** no log line produced by the request contains the secret

#### Scenario: Failure logs no secret
- **WHEN** the request fails after the secret has been read from the object store
- **THEN** no log line or error response contains it

### Requirement: Operator CLI parity
The `caelus` operator CLI MUST offer the same read as `get-deployment-bucket`, over the same service and subject to the same rules, including withholding the secret from an operator who is not the deployment's owner.

#### Scenario: Operator reads details
- **WHEN** an operator runs `caelus get-deployment-bucket` for a deployment
- **THEN** the same fields are reported as the API would report, with the secret withheld under the same rule
