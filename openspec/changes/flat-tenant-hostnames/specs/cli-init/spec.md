# Spec Delta

## ADDED Requirements

### Requirement: A hostname without a dot is kept as an application label

The client SHALL identify the hostname property by its schema title, matched
case-insensitively, the same rule the platform uses. It SHALL lowercase the entered value
and write it to the project file as entered. A value without a dot is an application label,
which the platform completes beneath the account's handle. When the account holds a handle,
the client SHALL show the resulting address by appending the reported `suffix`.

#### Scenario: A bare label is kept as a label

- **WHEN** the user enters `Photos` and the account's suffix is `-alice.freepod.app`
- **THEN** the project file records `photos`
- **AND** the client shows `photos-alice.freepod.app` as the address it will have

#### Scenario: A fully-qualified name is left intact

- **WHEN** the user enters a hostname containing a dot
- **THEN** the client lowercases it and records it as entered

## REMOVED Requirements

### Requirement: A hostname without a domain is completed from a platform domain
**Reason**: The platform completes bare labels beneath the owner's handle. A client-side
domain would put back the coupling this change removes.
**Migration**: See *A hostname without a dot is kept as an application label*.
