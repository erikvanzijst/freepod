## ADDED Requirements

### Requirement: Each instance provisions a size-reading token for the bucket size exporter

Each instance's provisioning SHALL mint an admin token for the bucket size exporter,
scoped to `ListBuckets` and `GetBucketInfo` and nothing else. It SHALL be stored in a
Kubernetes Secret in the instance's namespace, which the exporter reads. It SHALL be
distinct from the Caelus API's provisioning token, so either can be revoked or rotated
without the other.

Like the API's token, it SHALL NOT expire. It is held by a long-running process that
cannot mint its own replacement. As with every other provisioning step, re-running SHALL
keep an existing token whose secret is still held, and SHALL replace one whose secret
was lost.

#### Scenario: The exporter's token can only read

- **WHEN** the exporter's token is used to create, update or delete a bucket or key, or
  to read a key's secret
- **THEN** Garage refuses the request

#### Scenario: Re-running provisioning keeps the token

- **WHEN** provisioning runs again against an instance whose exporter token and Secret
  both exist
- **THEN** the same token remains valid and the Secret is unchanged
