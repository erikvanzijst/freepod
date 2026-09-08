## MODIFIED Requirements

### Requirement: The resolver answers the edge's routing and authentication question per connection
The platform MUST provide a resolver that the SSH edge consults on each connection, receiving the SSH username the client presented and the public key it offered, and returning either the upstream sidecar to connect to and the credential to present there, or a refusal.

The resolver MUST derive its answer from the platform's own records at the time of the request. It MUST NOT depend on a copy of those records held elsewhere — in a cluster object, a rendered file, or a cache that can outlive a change to the underlying record — because any such copy is a second source of truth that can disagree with the first and grant access the platform's records no longer authorize.

Consulting the resolver MUST NOT require the edge to be restarted or reconfigured when a deployment or a key is created or removed.

#### Scenario: A connection is resolved from current records
- **WHEN** a client connects with a username and offers a public key
- **THEN** the edge obtains the upstream target and the upstream credential from the resolver, derived from the platform's records as they stand at that moment

#### Scenario: A new deployment is reachable without reconfiguring the edge
- **WHEN** a deployment is created and its owner connects to it
- **THEN** the connection resolves without the edge having been restarted or reconfigured

#### Scenario: No copy of the answer exists to go stale
- **WHEN** the cluster is inspected
- **THEN** no object holds a routing record or a projection of any account's keys for this purpose

### Requirement: A deployment that no longer exists stops being routable by that fact alone
The resolver MUST refuse a username that names no deployment, and MUST refuse one whose deployment is not in a state that permits access. Ceasing to be routable MUST be a consequence of the deployment's own record, not of a separate cleanup step that could fail or be skipped.

A username MUST NOT resolve to a deployment other than the one that record names. Because the username is the deployment's own primary key, this holds by construction: no later deployment can be addressed by the identifier an earlier one carried, so no access can be carried across from a deployment that is gone.

#### Scenario: A deleted deployment is not routable
- **WHEN** a deployment is deleted and a client connects with its username
- **THEN** the connection is refused, without any routing object having had to be removed

#### Scenario: An unknown username is refused
- **WHEN** a client connects with a username naming no deployment
- **THEN** the connection is refused

#### Scenario: A deleted deployment's username is never inherited
- **WHEN** a deployment is deleted and further deployments are created
- **THEN** none of them is addressable by the deleted deployment's username

#### Scenario: There is no orphaned routing state to detect
- **WHEN** the platform sweeps for cluster objects no row accounts for
- **THEN** routing state is not among the classes it must look for, because none is created

## ADDED Requirements

### Requirement: The presented username is the deployment's id
The resolver MUST select a deployment by matching the presented SSH username against the deployment's id, and MUST match nothing else. A username matching a deployment's name, its namespace, or any other field MUST NOT resolve.

The id is the deployment's primary key, so at most one row can match: the lookup is unambiguous as a property of the data rather than of the query, and the resolver MUST NOT reduce a result set to one row to make it so. The id is also permanent and never reissued, so no later deployment can inherit an identifier an earlier one was addressed by.

The username MUST be matched in full. A prefix of an id MUST NOT resolve, however unambiguous it may be at the moment it is presented: whether a prefix identifies one deployment depends on what other deployments exist, so an identifier accepted on that basis could stop working because of an unrelated deployment created by someone else — and the edge's refusals disclose nothing, leaving the user no way to tell what happened.

A username that is not a well-formed id MUST be refused as an unknown username, and MUST be refused without querying the store, so that a malformed username is never recorded as a failure to answer.

#### Scenario: A deployment id resolves its deployment
- **WHEN** a client presents a deployment's id as its username and offers a registered key
- **THEN** the connection is admitted and proxied to that deployment's sidecar

#### Scenario: A deployment's internal names do not resolve
- **WHEN** a client presents a deployment's name, or its namespace, as its username
- **THEN** the connection is refused as an unknown username, even though a deployment carries both

#### Scenario: A prefix of an id does not resolve
- **WHEN** a client presents a leading portion of a deployment's id as its username
- **THEN** the connection is refused

#### Scenario: A malformed username never reaches the store
- **WHEN** a client presents a username that is not a well-formed id
- **THEN** it is refused as an unknown username, and the store is not queried

#### Scenario: The lookup cannot be ambiguous
- **WHEN** the resolver looks a username up
- **THEN** the identifier it matches on is a primary key, and the lookup does not discard additional matches to produce an answer

### Requirement: The upstream account is the deployment's release name
Having selected a deployment by its id, the resolver MUST present that deployment's release name as the username to the upstream sidecar, and MUST address the sidecar within that deployment's namespace.

The identifier a client presents and the account the edge logs in as are two different facts. The client-facing one identifies a deployment among all deployments; the upstream one need only be the account the sidecar was rendered with, which is the release name. Requiring them to be the same string would force every tenant's sidecar to be re-rendered whenever the client-facing identifier changed.

#### Scenario: The upstream login is the release name
- **WHEN** a connection presenting a deployment's id is admitted
- **THEN** the edge authenticates to that deployment's sidecar as the deployment's release name

#### Scenario: No chart is re-rendered for this
- **WHEN** the identifier clients present changes
- **THEN** no deployment is reconciled and no sidecar is re-rendered, because nothing in the tenant's namespace names the client-facing identifier
