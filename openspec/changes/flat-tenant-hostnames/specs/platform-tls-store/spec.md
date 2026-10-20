# Spec Delta

## ADDED Requirements

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

## REMOVED Requirements

### Requirement: Membership is derived from the certificates that exist
**Reason**: The platform no longer issues per-account certificates, so there is no membership to
derive. Tenant hostnames are served by the default certificate.
**Migration**: The membership list is left as last written. See *Ownership is split by field,
not by object*.

### Requirement: The list is written with a compare-and-swap precondition
**Reason**: Nothing writes the membership list any more.
**Migration**: None.

### Requirement: Any reconcile converges the whole store
**Reason**: Reconciles no longer touch the store.
**Migration**: None.

### Requirement: Ownership is split by field, not by object
**Reason**: The reconciler no longer writes the membership list.
**Migration**: See *Only the default certificate is managed*.
