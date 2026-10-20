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

### Requirement: Only the default certificate is managed

Infrastructure code MUST own the store's default certificate, written declaratively, and MUST
omit the membership list entirely rather than declaring it, even as an empty list. No platform
component writes the membership list. It keeps whatever entries it last held, which serve
retired tenant hostnames until a later change removes them.

#### Scenario: Infrastructure code owns the default certificate

- **WHEN** the store is applied by infrastructure code
- **THEN** it sets the default certificate and omits the membership list entirely

#### Scenario: The membership list is left as it is

- **WHEN** deployments are created, updated, reconciled or deleted
- **THEN** the store's membership list is not written

#### Scenario: Applying the store does not clear membership

- **WHEN** infrastructure code re-applies the store
- **THEN** the entries already in the membership list remain
