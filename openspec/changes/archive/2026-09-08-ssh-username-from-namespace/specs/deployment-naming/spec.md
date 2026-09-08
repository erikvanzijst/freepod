## REMOVED Requirements

### Requirement: Unique namespace-name constraint for active deployments

**Reason**: Subsumed by `deployment-namespace` § *A namespace is globally unique and is never reissued*. A unique namespace admits at most one deployment row, so a duplicate `(namespace, name)` pair is unreachable and the partial index guards nothing the stronger constraint does not already guard. Keeping it would also state a weaker promise beside a stronger one — it permits reuse after deletion, which the namespace constraint now forbids — and that reads as a deliberate exception rather than as redundancy.

**Migration**: The `uq_deployment_ns_name_active` index is dropped in the same migration that adds the unconditional unique index on `namespace`. No behavior a caller can observe changes: every write the dropped index rejected is still rejected, by the namespace constraint, and earlier.

## ADDED Requirements

### Requirement: The deployment name is unique within its namespace as a consequence
A deployment's name MUST be unique within its namespace, so that it is unambiguous as a Helm release name and as the account the SSH edge presents to that deployment's sidecar. This MUST follow from the namespace being unique per deployment rather than from a constraint on the pair.

The name MUST NOT be relied on as a globally unique identifier. It is generated from the product name and a 6-character random suffix, and nothing enforces uniqueness across namespaces; a component that selects a deployment by name alone can select the wrong one.

#### Scenario: One release per namespace
- **WHEN** a deployment's namespace is inspected
- **THEN** it contains exactly one deployment's Helm release, so the name within it names one thing

#### Scenario: The same name in two namespaces is permitted
- **WHEN** two deployments of the same product are created and receive the same generated name
- **THEN** both are accepted, because they occupy different namespaces

#### Scenario: Nothing addresses a deployment by name alone
- **WHEN** a component resolves which deployment to act on from an externally supplied identifier
- **THEN** it MUST use the namespace, not the name
