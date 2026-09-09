# platform-tls-store Specification

## Purpose
The certificate store the ingress controller serves from: a single platform-owned object whose
membership is derived from the certificates that exist, written safely by concurrent workers,
and owned field by field so that neither Terraform nor the ingress controller's own chart can
revert it.

## Requirements
### Requirement: The store is a platform-owned object, not a chart value

The certificate store MUST be an object the platform owns, in the namespace holding the
certificates, and MUST NOT be rendered by the ingress controller's Helm release.

An object rendered by a chart is reset to the chart's view of it on every upgrade of that
chart. A store whose membership is maintained by the reconciler and whose shape is maintained
by a release upgrade has a failure mode where an unrelated ingress-controller upgrade drops
every account's certificate at once, and it surfaces as the whole fleet being served the wrong
certificate.

#### Scenario: An ingress-controller upgrade does not disturb membership

- **WHEN** the ingress controller's Helm release is upgraded
- **THEN** the store still lists every account certificate it listed before

#### Scenario: The chart renders no store

- **WHEN** the ingress controller's rendered manifests are inspected
- **THEN** they contain no certificate store object

### Requirement: The store and its certificates share a namespace

The store MUST be in the same namespace as every certificate secret it names, including the
platform's default certificate.

Certificate references in the store carry a name and no namespace, and are resolved in the
store's own namespace. There is no cross-namespace form to reach for.

#### Scenario: A referenced secret is resolvable

- **WHEN** the store names a certificate secret
- **THEN** that secret exists in the store's own namespace

### Requirement: Ownership is split by field, not by object

The default certificate and the membership list MUST be owned by different actors and written
by different mechanisms: the default certificate declaratively by infrastructure code, the
membership list by the reconciler at runtime. Each MUST write only the fields it owns, MUST
omit the fields it does not — declaring a field, even as an empty value, claims ownership of it —
and neither MUST override the other's ownership.

Splitting by field is what lets the object be created and shaped declaratively while its
membership changes with the fleet. Overriding the other's ownership — which the tooling offers
as a way past a conflict — would let the reconciler take the default certificate and drop it on
its next write, leaving connections with no fallback.

#### Scenario: Infrastructure code owns the default certificate

- **WHEN** the store is applied by infrastructure code
- **THEN** it sets the default certificate and omits the membership list entirely, rather than
  setting it to an empty one — declaring the field claims ownership of it, and the list is
  atomic, so an empty declaration makes every later write by the reconciler a conflict

#### Scenario: The reconciler owns the membership list

- **WHEN** the reconciler writes the store
- **THEN** it sets the membership list and does not set the default certificate

#### Scenario: Ownership is never forced

- **WHEN** the reconciler writes the store
- **THEN** it does not override another actor's ownership of any field

#### Scenario: The reconciler updates the store but never creates it

- **WHEN** the reconciler is about to write membership and the store does not exist
- **THEN** it refuses rather than creating one, because a store it created would carry no default
  certificate and leave connections matching nothing with no fallback

#### Scenario: An absent membership list is not an obstacle

- **WHEN** the reconciler writes membership to a store that has never had a membership list
- **THEN** the write succeeds and the list is created by it

### Requirement: Membership is derived from the certificates that exist

The membership list MUST be computed from the certificate secrets present in the namespace,
not from the platform's own records of which accounts should have one.

The question is which certificates can be served, and the cluster is authoritative for it. A
list built from the database can name a secret that has not been issued yet — which the ingress
controller reports as an error on every reload — and can omit one that has.

#### Scenario: Only issued certificates are listed

- **WHEN** an account's certificate has been requested but not yet issued
- **THEN** it is not in the list, and appears once its secret exists

#### Scenario: The list never names a missing secret

- **WHEN** the store is inspected
- **THEN** every secret it names exists

### Requirement: The list is written with a compare-and-swap precondition

Every write of the membership list MUST carry the version of the object it was computed
against, so that a write made from a stale view is rejected rather than applied. A rejected
write MUST be retried from a fresh read, a bounded number of times.

The reconciler runs as several concurrent processes. Two of them writing a whole list computed
at different moments is a lost update: the later write drops the entry the earlier one added,
and an account's applications are served the wrong certificate with nothing to indicate why.
Recomputing the whole list does not avoid this — it is the mechanism of it.

#### Scenario: A stale write is refused

- **WHEN** a worker writes the list computed against a version of the object that has since
  changed
- **THEN** the write is refused

#### Scenario: A refused write converges

- **WHEN** a write is refused
- **THEN** the worker reads again, recomputes, and writes, and the resulting list contains both
  workers' certificates

#### Scenario: Concurrent additions both survive

- **WHEN** two workers add certificates for different accounts at the same time
- **THEN** the store ends up listing both

### Requirement: Any reconcile converges the whole store

Because the list is derived from the whole namespace rather than from the deployment being
reconciled, any reconcile that writes it MUST bring it to the complete correct set, correcting
drift for every account rather than only the one at hand. A reconcile that finds the list
already correct MUST NOT write.

This is what removes the need for a periodic sweep: correction is a side effect of ordinary
work, and the common case costs a read.

#### Scenario: Drift is corrected by unrelated work

- **WHEN** an account's certificate is missing from the list and any deployment reconciles
- **THEN** the list is corrected

#### Scenario: A correct list is not rewritten

- **WHEN** a reconcile finds the list already matches the certificates that exist
- **THEN** no write is made

### Requirement: A listed certificate is served to routes that do not reference it

A certificate in the store MUST be served for connections whose name it matches, to routes
defined in any namespace, without those routes referencing it.

This is the property the whole design rests on: certificate selection happens by server name
during the handshake, before routing, so a certificate in the store reaches routes that know
nothing about it. It is what removes any need to copy certificate material into tenant
namespaces.

#### Scenario: An account certificate is served for its own names

- **WHEN** a connection arrives with a server name matching an account's certificate
- **THEN** that certificate is served, and not the default one

#### Scenario: No route references the certificate

- **WHEN** the routes serving an account's applications are inspected
- **THEN** none of them names the account's certificate or its secret

#### Scenario: Unmatched names still get the default

- **WHEN** a connection arrives with a server name no listed certificate matches
- **THEN** the default certificate is served, as before
