# Spec Delta

## MODIFIED Requirements

### Requirement: The reason is one of a closed set

A power row's reason SHALL be one of `manual`, `payment` or `maintenance`, enforced by the database.
- `manual` covers an owner, administrator or operator action, in either direction.
- `payment` is reserved for stopping a deployment in payment arrears. No component produces it yet, but the schema SHALL accept it, so that the later phase adds a producer without a migration.
- `maintenance` is a stop the platform holds while an operator works on the deployment. Only the platform records it, and only the platform lifts it.

#### Scenario: An unknown reason is rejected

- **WHEN** a power row is written with a reason other than `manual`, `payment` or `maintenance`
- **THEN** the database rejects the write

#### Scenario: A maintenance stop is accepted

- **WHEN** a power row is written with reason `maintenance`
- **THEN** the database accepts it
